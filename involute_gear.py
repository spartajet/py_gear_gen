import numpy as np
from math import *
from mathutils import *
import sys
from svgwrite.path import Path
from svgwrite import mm, Drawing


class DimensionException(Exception):
    pass

class InvoluteGear:
    def __init__(self, module=1, teeth=30, pressure_angle_deg=20, fillet=0, backlash=0,
                 max_steps=100, arc_step_size=0.1, ring=False):
        '''
        Construct an involute gear, ready for generation using one of the generation methods.
        :param module: The 'module' of the gear. (Diameter / Teeth)
        :param teeth: How many teeth in the desired gear.
        :param pressure_angle_deg: The pressure angle of the gear in DEGREES.
        :param fillet: The radius of the fillet connecting a tooth to the root circle. NOT WORKING in ring gear.
        :param backlash: The circumfrential play between teeth, if meshed with another gear of the same backlash held stationary
        :param max_steps: Maximum steps allowed to generate the involute profile. Higher is more accurate.
        :param arc_step_size: The step size used for generating arcs.
        :param ring: True if this is a ring (internal) gear, otherwise False.
        '''

        pressure_angle = radians(pressure_angle_deg)
        self.module = module
        self.teeth = teeth
        self.pressure_angle = pressure_angle

        # Addendum is the height above the pitch circle that the tooth extends to
        self.addendum = module
        # Dedendum is the depth below the pitch circle the root extends to. 1.157 is a std value allowing for clearance.
        self.dedendum = 1.157 * module

        # If the gear is a ring gear, then the clearance needs to be on the other side
        if ring:
            temp = self.addendum
            self.addendum = self.dedendum
            self.dedendum = temp


        # The radius of the pitch circle
        self.pitch_radius = (module * teeth) / 2
        # The radius of the base circle, used to generate the involute curve
        self.base_radius = cos(pressure_angle) * self.pitch_radius
        # The radius of the gear's extremities
        self.outer_radius = self.pitch_radius + self.addendum
        # The radius of the gaps between the teeth
        self.root_radius = self.pitch_radius - self.dedendum

        # The radius of the fillet circle connecting the tooth to the root circle
        self.fillet_radius = fillet if not ring else 0

        # The angular width of a tooth and a gap. 360 degrees divided by the number of teeth
        self.theta_tooth_and_gap = pi * 2 / teeth
        # Converting the circumfrential backlash into an angle
        angular_backlash = (backlash / 2 / self.pitch_radius)
        # The angular width of the tooth at the pitch circle minus backlash, not taking the involute into account
        self.theta_tooth = self.theta_tooth_and_gap / 2 + (-angular_backlash if not ring else angular_backlash)
        # Where the involute profile intersects the pitch circle, found on iteration.
        self.theta_pitch_intersect = None
        # The angular width of the full tooth, at the root circle
        self.theta_full_tooth = None

        self.max_steps = max_steps
        self.arc_step_size = arc_step_size

    def generate_half_tooth(self):
        '''
        Generate half an involute profile, ready to be mirrored in order to create one symmetrical involute tooth
        :return: A numpy array, of the format [[x1, x2, ... , xn], [y1, y2, ... , yn]]
        '''
        # Theta is the angle around the circle, however PHI is simply a parameter for iteratively building the involute
        phis = np.linspace(0, pi, self.max_steps)
        points = []
        reached_limit = False
        self.theta_pitch_intersect = None

        for phi in phis:
            x = (self.base_radius * cos(phi)) + (phi * self.base_radius * sin(phi))
            y = (self.base_radius * sin(phi)) - (phi * self.base_radius * cos(phi))
            point = (x, y)
            dist, theta = cart_to_polar(point)

            if self.theta_pitch_intersect is None and dist >= self.pitch_radius:
                self.theta_pitch_intersect = theta
                self.theta_full_tooth = self.theta_pitch_intersect * 2 + self.theta_tooth
            elif self.theta_pitch_intersect is not None and theta >= self.theta_full_tooth / 2:
                reached_limit = True
                break

            if dist >= self.outer_radius:
                points.append(polar_to_cart((self.outer_radius, theta)))
            elif dist <= self.root_radius:
                points.append(polar_to_cart((self.root_radius, theta)))
            else:
                points.append((x,y))

        if not reached_limit:
            raise Exception("Couldn't complete tooth profile.")

        return np.transpose(points)

    def generate_root(self):
        '''
        Generate the gap between teeth, for the first tooth
        :return: A numpy array, of the format [[x1, x2, ... , xn], [y1, y2, ... , yn]]
        '''
        root_arc_length = (self.theta_tooth_and_gap - self.theta_full_tooth) * self.root_radius

        points_root = []
        for theta in np.arange(self.theta_full_tooth, self.theta_tooth_and_gap, self.arc_step_size / self.root_radius):
            # The current circumfrential position we are in the root arc, starting from 0
            arc_position = (theta - self.theta_full_tooth) * self.root_radius
            # If we are in the extemities of the root arc (defined by fillet_radius), then we are in a fillet
            in_fillet = min((root_arc_length - arc_position), arc_position) < self.fillet_radius

            r = self.root_radius

            if in_fillet:
                # Add a circular profile onto the normal root radius to form the fillet.
                # High near the edges, small towards the centre
                # The min() function handles the situation where the fillet size is massive and overlaps itself
                circle_pos = min(arc_position, (root_arc_length - arc_position))
                r = r + (self.fillet_radius - sqrt(pow(self.fillet_radius, 2) - pow(self.fillet_radius - circle_pos, 2)))
            points_root.append(polar_to_cart((r, theta)))
        return np.transpose(points_root)

    def generate_tooth(self):
        '''
        Generate only one involute tooth, without an accompanying tooth gap
        :return: A numpy array, of the format [[x1, x2, ... , xn], [y1, y2, ... , yn]]
        '''

        points_first_half = self.generate_half_tooth()
        points_second_half = np.dot(rotation_matrix(self.theta_full_tooth), np.dot(flip_matrix(False, True), points_first_half))
        points_second_half = np.flip(points_second_half, 1)
        return np.concatenate((points_first_half, points_second_half), axis=1)

    def generate_tooth_and_gap(self):
        '''
        Generate only one tooth and one root profile, ready to be duplicated by rotating around the gear center
        :return: A numpy array, of the format [[x1, x2, ... , xn], [y1, y2, ... , yn]]
        '''

        points_tooth = self.generate_tooth()
        points_root = self.generate_root()
        points_module = np.concatenate((points_tooth, points_root), axis=1)
        return points_module

    def generate_gear(self):
        '''
        Generate the gear profile, and return a sequence of co-ordinates representing the outline of the gear
        :return: A numpy array, of the format [[x1, x2, ... , xn], [y1, y2, ... , yn]]
        '''

        points_tooth_and_gap = self.generate_tooth_and_gap()
        points_teeth = [np.dot(rotation_matrix(self.theta_tooth_and_gap * n), points_tooth_and_gap) for n in range(self.teeth)]
        points_gear = np.concatenate(points_teeth, axis=1)
        points_gear = np.dot(rotation_matrix(-self.theta_full_tooth / 2), points_gear)
        return points_gear

    def get_point_list(self):
        '''
        Generate the gear profile, and return a sequence of co-ordinates representing the outline of the gear
        :return: A numpy array, of the format [[x1, y2], [x2, y2], ... , [xn, yn]]
        '''

        gear = self.generate_gear()
        return np.transpose(gear)

    def get_svg(self, unit=mm):
        '''
        Generate an SVG Drawing based of the generated gear profile.
        :param unit: None or a unit within the 'svgwrite' module, such as svgwrite.mm, svgwrite.cm
        :return: An svgwrite.Drawing object populated only with the gear path.
        '''

        points = self.get_point_list()
        width, height = np.ptp(points, axis=0)
        left, top = np.min(points, axis=0)
        size = (width*unit, height*unit) if unit is not None else (width,height)
        dwg = Drawing(size=size, viewBox='{} {} {} {}'.format(left,top,width,height))
        p = Path('M')
        p.push(points)
        p.push('Z')
        dwg.add(p)
        return dwg

def error_out(s, *args):
    sys.stderr.write(s + "\n")