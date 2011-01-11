#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2011, Florent Lamiraux, Thomas Moulard, JRL, CNRS/AIST
#
# This file is part of dynamic-graph.
# dynamic-graph is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# dynamic-graph is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Lesser Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with
# dynamic-graph. If not, see <http://www.gnu.org/licenses/>.

from dynamic_graph.sot.core import RobotSimu, VectorConstant, \
    MatrixConstant, RPYToMatrix, Derivator_of_Vector, FeaturePoint6d, \
    FeaturePoint6dRelative, FeatureGeneric, FeatureJointLimits, \
    Compose_R_and_T, Task, Constraint, GainAdaptive, SOT, \
    MatrixHomoToPoseRollPitchYaw

from dynamic_graph.sot.dynamics.humanoid_robot import HumanoidRobot
from dynamic_graph.sot.dynamics.hrp2 import Hrp2

from dynamic_graph import enableTrace, plug

# Robotviewer is optional
enableRobotViewer = True
try:
    import robotviewer
except ImportError:
    enableRobotViewer = False



def displayHomogeneousMatrix(matrix):
    """
    Display nicely a 4x4 matrix (usually homogeneous matrix).
    """
    import itertools

    matrix_tuple = tuple(itertools.chain.from_iterable(matrix))

    formatStr = ''
    for i in xrange(4*4):
        formatStr += '{0[' + str(i) + ']: <10} '
        if i != 0 and (i + 1) % 4 == 0:
            formatStr += '\n'
    print formatStr.format(matrix_tuple)

def toList(tupleOfTuple):
    result = [[0, 0, 0, 0],
              [0, 0, 0, 0],
              [0, 0, 0, 0],
              [0, 0, 0, 0]]
    for i in xrange(4):
        for j in xrange(4):
            result[i][j] = tupleOfTuple[i][j]
    return result

def toTuple(listOfList):
    return ((listOfList[0][0], listOfList[0][1],
             listOfList[0][2], listOfList[0][3]),

            (listOfList[1][0], listOfList[1][1],
             listOfList[1][2], listOfList[1][3]),

            (listOfList[2][0], listOfList[2][1],
             listOfList[2][2], listOfList[2][3]),

            (listOfList[3][0], listOfList[3][1],
             listOfList[3][2], listOfList[3][3]))

def smallToFull(config):
    res = (config + 10*(0.,))
    return res

class QuasiStaticWalking:
    leftFoot = 0
    rightFoot = 1

    stateCoM_doubleToSingle = 0
    stateLifting = 1
    stateLanding = 2
    stateCoM_singleToDouble = 3

    time = {
        stateCoM_doubleToSingle : 1.,
        stateLifting :            5.,
        stateLanding :            5.,
        stateCoM_singleToDouble : 1.
        }

    footAltitude = 0.1

    robot = None
    supportFoot = None
    state = None
    nextStateSwitch = None
    initialFootPose = dict()
    t = None


    def __init__(self, robot):
        self.robot = robot
        self.supportFoot = self.leftFoot
        self.state = self.stateCoM_doubleToSingle
        self.nextStateSwitch = 0 # Next switch is now!

        self.initialFootPose['left-ankle'] = \
            self.robot.dynamicRobot.signal('left-ankle').value
        self.initialFootPose['right-ankle'] = \
            self.robot.dynamicRobot.signal('right-ankle').value

        self.t = None # Will be updated through the update method.

        self.robot.tasks['left-ankle'].signal('controlGain').value = 1.
        self.robot.tasks['right-ankle'].signal('controlGain').value = 1.


    # Move CoM to a particular operational point (usually left or right ankle).
    # op supports a special value called origin to move back to double support.
    def moveCoM(self, op):
        x = 0.
        y = 0.

        if op == 'origin':
            x = 0.
            y = 0.
        else:
            x = robot.dynamicRobot.signal(op).value[0][3]
            y = robot.dynamicRobot.signal(op).value[1][3]

        z = robot.featureComDes.signal('errorIN').value[2]
        self.robot.featureComDes.signal('errorIN').value = (x, y, z)

    def liftFoot(self, op):
        sdes = toList(robot.dynamicRobot.signal(op).value)
        sdes[2][3] += self.footAltitude # Increment altitude.
        robot.features[op].reference.signal('position').value = toTuple(sdes)

    def landFoot(self, op):
        robot.features[op].reference.signal('position').value = \
            self.initialFootPose[op]

    def supportFootStr(self):
        if self.supportFoot == self.leftFoot:
            return 'left-ankle'
        else:
            return 'right-ankle'

    def flyingFootStr(self):
        if self.supportFoot == self.leftFoot:
            return 'right-ankle'
        else:
            return 'left-ankle'

    def do(self, state):
        if state == self.stateCoM_doubleToSingle:
            self.do_stateCoM_doubleToSingle()
        elif state == self.stateLifting:
            self.do_stateLifting()
        elif state == self.stateLanding:
            self.do_stateLanding()
        else:
            self.do_stateCoM_singleToDouble()


    def do_stateCoM_doubleToSingle(self):
        self.moveCoM(self.supportFootStr())
        self.nextStateSwitch = self.t + self.time[self.stateCoM_doubleToSingle]

    def do_stateLifting(self):
        self.liftFoot(self.flyingFootStr())
        self.nextStateSwitch = self.t + self.time[self.stateLifting]

    def do_stateLanding(self):
        self.landFoot(self.flyingFootStr())
        self.nextStateSwitch = self.t + self.time[self.stateLanding]

    def do_stateCoM_singleToDouble(self):
        self.moveCoM('origin')
        self.nextStateSwitch = self.t + self.time[self.stateCoM_singleToDouble]

        # Switch support foot.
        if self.supportFoot == self.leftFoot:
            self.supportFoot = self.rightFoot
        else:
            self.supportFoot = self.leftFoot


    def update(self, t):
        self.t = t

        # If step is finished.
        if self.t >= self.nextStateSwitch:
            # Change the current state.
            if self.state == self.stateCoM_singleToDouble:
                self.state = 0
            else:
                self.state += 1

            # Trigger actions to move to next state.
            self.do(self.state)

robot = Hrp2("robot", True)

# Initialize robotviewer is possible.
clt = None
if enableRobotViewer:
    try:
        clt = robotviewer.client()
    except:
        enableRobotViewer = False

timeStep = .02

class Solver:
    robot = None
    sot = None

    def __init__(self, robot):
        self.robot = robot
        self.sot = SOT('solver')
        self.sot.signal('damping').value = 1e-6
        self.sot.setNumberDofs(self.robot.dimension)

        if robot.robotSimu:
            plug(self.sot.signal('control'), robot.robotSimu.signal('control'))
            plug(self.robot.robotSimu.signal('state'),
                 self.robot.dynamicRobot.signal('position'))

solver = Solver (robot)

# Push tasks
#  Feet tasks.
solver.sot.push(robot.name + '.task.right-ankle')
solver.sot.push(robot.name + '.task.left-ankle')

#  Center of mass
# FIXME: trigger segv at exit.
solver.sot.push(robot.name + '.task.com')


# Main.

#  Parameters
steps = 3

#  Initialization
quasiStaticWalking = QuasiStaticWalking(robot)

#  Total time computation
stepTime = reduce(lambda acc, (u,v): acc + v,
                  quasiStaticWalking.time.iteritems(), 0.)
totalSteps = int((stepTime / timeStep) * steps)

#  Main loop
t = 0
for i in xrange(totalSteps + 1):
    t += timeStep
    robot.robotSimu.increment(timeStep)

    quasiStaticWalking.update(t)

    if clt:
        clt.updateElementConfig(
            'hrp', smallToFull(robot.robotSimu.signal('state').value))

#  Security: switch back to double support.
quasiStaticWalking.moveCoM('origin')
duration = quasiStaticWalking.time[quasiStaticWalking.stateCoM_singleToDouble]

for i in xrange(int(duration / timeStep)):
    t += timeStep
    robot.robotSimu.increment(timeStep)

    if clt:
        clt.updateElementConfig(
            'hrp', smallToFull(robot.robotSimu.signal('state').value))


print "FINISHED"