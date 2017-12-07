#!/usr/bin/env python
import rospy
from std_msgs.msg import Int32
from geometry_msgs.msg import PoseStamped, Pose
from styx_msgs.msg import TrafficLightArray, TrafficLight
from styx_msgs.msg import Lane
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from light_classification.tl_classifier import TLClassifier
import tf
import cv2
import yaml
import math
import PyKDL
from tf.transformations import euler_from_quaternion

STATE_COUNT_THRESHOLD = 3

class TLDetector(object):
    def __init__(self):
        rospy.init_node('tl_detector')

        self.pose = None
        self.waypoints = None
        self.camera_image = None
        self.lights = []

        sub1 = rospy.Subscriber('/current_pose', PoseStamped, self.pose_cb)
        sub2 = rospy.Subscriber('/base_waypoints', Lane, self.waypoints_cb)

        '''
        /vehicle/traffic_lights provides you with the location of the traffic light in 3D map space and
        helps you acquire an accurate ground truth data source for the traffic light
        classifier by sending the current color state of all traffic lights in the
        simulator. When testing on the vehicle, the color state will not be available. You'll need to
        rely on the position of the light and the camera image to predict it.
        '''
        sub3 = rospy.Subscriber('/vehicle/traffic_lights', TrafficLightArray, self.traffic_cb)
        sub6 = rospy.Subscriber('/image_color', Image, self.image_cb)

        config_string = rospy.get_param("/traffic_light_config")
        self.config = yaml.load(config_string)

        #setup stop line positions in TrafficLight-style object for use later on closestwaypoint
        self.stop_line_positions_poses = []
        for stop in self.config['stop_line_positions']:
            s = TrafficLight()
            s.pose.pose.position.x = stop[0]
            s.pose.pose.position.y = stop[1]
            s.pose.pose.position.z = 0
            #rospy.loginfo('adding stop_line_position - [{},{}]'.format(stop[0], stop[1]))
            self.stop_line_positions_poses.append(s)


        self.upcoming_red_light_pub = rospy.Publisher('/traffic_waypoint', Int32, queue_size=1)

        self.bridge = CvBridge()
        self.light_classifier = TLClassifier()
        self.listener = tf.TransformListener()

        self.state = TrafficLight.UNKNOWN
        self.last_state = TrafficLight.UNKNOWN
        self.last_wp = -1
        self.state_count = 0

        rospy.loginfo('Traffic light detector initialized')
        rospy.spin()

    def pose_cb(self, msg):
        self.pose = msg

    def waypoints_cb(self, waypoints):
        self.waypoints = waypoints

    def traffic_cb(self, msg):
        self.lights = msg.lights

    def image_cb(self, msg):
        """Identifies red lights in the incoming camera image and publishes the index
            of the waypoint closest to the red light's stop line to /traffic_waypoint

        Args:
            msg (Image): image from car-mounted camera

        """
        self.has_image = True
        self.camera_image = msg
        light_wp, state = self.process_traffic_lights()
        #rospy.loginfo("process_traffic_lights: {},{}".format(light_wp, state))

        '''
        Publish upcoming red lights at camera frequency.
        Each predicted state has to occur `STATE_COUNT_THRESHOLD` number
        of times till we start using it. Otherwise the previous stable state is
        used.
        '''
        if self.state != state:
            self.state_count = 0
            self.state = state
        elif self.state_count >= STATE_COUNT_THRESHOLD:
            self.last_state = self.state
            light_wp = light_wp if state == TrafficLight.RED else -1
            self.last_wp = light_wp
            self.upcoming_red_light_pub.publish(Int32(light_wp))
        else:
            self.upcoming_red_light_pub.publish(Int32(self.last_wp))
        self.state_count += 1

    def get_distance_between_poses( self, a, b ):
        return math.sqrt( (a.position.x - b.position.x)**2 + (a.position.y - b.position.y)**2 )

    def get_closest_waypoint(self, pose, waypoints,  mode=None ):
        """Identifies the closest path waypoint to the given position
            https://en.wikipedia.org/wiki/Closest_pair_of_points_problem
        Args:
            pose (Pose): position to match a waypoint to
            waypoints (list): the reference list of waypoints to search on
            mode: "nearest" -> returns nearest waypoint regardless of direction. 
                  "forward" -> returns nearest waypoint in forward direction

        Returns:
            int: index of the closest waypoint in self.waypoints

        """

        if waypoints==None or pose==None:
            rospy.logerr("No waypoint list or pose specified in get_closest_waypoint")
            return -1

        #implement search, nearest
        min_dist = float("inf")
        min_idx = None
        search_range = 400 

        for i, wp in enumerate(waypoints):
            dist = self.get_distance_between_poses( wp.pose.pose, pose )

            if (dist < min_dist) and (dist<search_range):
                if (mode == None ):
                    min_dist = dist
                    min_idx = i
                elif( mode == "forward" ): 
                    # pose quaternion
                    p_q = PyKDL.Rotation.Quaternion(pose.orientation.x,
                            pose.orientation.y,
                            pose.orientation.z,
                            pose.orientation.w)


                    # let's use scalar product to find the angle between the car orientation vector and car/base_point vector
                    car_orientation = p_q * PyKDL.Vector(1.0, 0.0, 0.0)


                    xyz_position = pose.position
                    quaternion_orientation = pose.orientation

                    p = xyz_position
                    qo = quaternion_orientation

                    p_list = [p.x, p.y, p.z]
                    qo_list = [qo.x, qo.y, qo.z, qo.w]
                    euler = euler_from_quaternion(qo_list)
                    yaw_rad = euler[2]
                    print("yaw_rad {0}, car_orientation {1}".format(yaw_rad, car_orientation))
                    # example output
                    # yaw_rad 0.0872679286763, car_orientation [    0.996195,   0.0871572,           0]
                    # yaw_rad 0.00123239892429, car_orientation [    0.999999,   0.0012324,           0]
                    # yaw_rad 0.0872679286763, car_orientation [    0.996195,   0.0871572,           0]
                   pass

                



            
        
        return min_idx

    def get_light_state(self, light):
        """Determines the current color of the traffic light

        Args:
            light (TrafficLight): light to classify

        Returns:
            int: ID of traffic light color (specified in styx_msgs/TrafficLight)

        """
        if(not self.has_image):
            self.prev_light_loc = None
            return False

        cv_image = self.bridge.imgmsg_to_cv2(self.camera_image, "bgr8")

        #Get classification
        return self.light_classifier.get_classification(cv_image)

    def process_traffic_lights(self):
        """Finds closest visible traffic light, if one exists, and determines its
            location and color

        Returns:
            int: index of waypoint closer to the upcoming stop line for a traffic light (-1 if none exists)
            int: ID of traffic light color (specified in styx_msgs/TrafficLight)

        """
        light = None

        # If there is a signal in sight, returns the car waypoint right before the stop line, alongside
        # with signal status

        # Steps to perform:
        # 1. Find the next upcoming light position from car pose given a certain range
        # 2. Find the stop_line_position before such traffic signal position
        # 3. Find the waypoint just before and this stop_line_position 

        if(self.pose==None):
            return -1, TrafficLight.UNKNOWN


        #TODO find the closest visible traffic light (if one exists)
        # 1. Find upcoming light position from our current car pose
        light_idx = self.get_closest_waypoint( self.pose.pose, self.lights )  # foward look

        if light_idx == None:
            rospy.loginfo('couldn\'t find light index for car pose: {},{}'.format(self.pose.pose.position.x, self.pose.pose.position.y)) 
            return -1, TrafficLight.UNKNOWN

        # 2. Find the stop_line_position closest to the found light index and make sure its the upcoming one for the car
        stop_line_idx    = self.get_closest_waypoint( self.lights[light_idx].pose.pose, self.stop_line_positions_poses ) # closest look
        stop_forward_idx = self.get_closest_waypoint( self.pose.pose, self.stop_line_positions_poses )  # fowards look TODO

        if(stop_line_idx != stop_forward_idx):
            #likely car is away from stop line still ?
            rospy.loginfo('traffic light upcoming but there\s no stop line position found')
            return -1, TrafficLight.UNKNOWN

        # 3. Find the car waypoint closest to the stop line
        stop_waypoint_idx = self.get_closest_waypoint( 
                self.stop_line_positions_poses[stop_line_idx].pose.pose, 
                self.waypoints.waypoints )  

        if( stop_waypoint_idx == None ):
            rospy.loginfo('Couldnt find waypoint in process_traffic_lights()')
            return -1, TrafficLight.UNKNOWN

        #TODO. 
        # add glue for real classifer here:
        #
        # self.get_light_state( self.lights[light_idx] )
        # 
        # using sim state for now
        state = self.lights[light_idx].state  #this is only valid within simulator

        return stop_waypoint_idx, state

if __name__ == '__main__':
    try:
        TLDetector()
    except rospy.ROSInterruptException:
        rospy.logerr('Could not start traffic node.')
