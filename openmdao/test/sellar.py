""" Test objects for the sellar two discipline problem.
From Sellar's analytic problem.

    Sellar, R. S., Batill, S. M., and Renaud, J. E., "Response Surface Based, Concurrent Subspace
    Optimization for Multidisciplinary System Design," Proceedings References 79 of the 34th AIAA
    Aerospace Sciences Meeting and Exhibit, Reno, NV, January 1996.
"""

import numpy as np

from openmdao.components.paramcomp import ParamComp
from openmdao.core.component import Component
from openmdao.core.group import Group


class SellarDis1(Component):
    """Component containing Discipline 1 -- no derivatives version."""

    def __init__(self):
        super(SellarDis1, self).__init__()

        # Global Design Variable
        self.add_param('z', val=np.zeros(2))

        # Local Design Variable
        self.add_param('x', val=0.)

        # Coupling parameter
        self.add_param('y2', val=0.)

        # Coupling output
        self.add_output('y1', val=0.)

    def solve_nonlinear(self, params, unknowns, resids):
        """Evaluates the equation
        y1 = z1**2 + z2 + x1 - 0.2*y2"""

        z1 = params['z'][0]
        z2 = params['z'][1]
        x1 = params['x']
        y2 = params['y2']

        unknowns['y1'] = z1**2 + z2 + x1 - 0.2*y2


class SellarDis1withDerivatives(SellarDis1):
    """Component containing Discipline 1 -- derivatives version."""

    def jacobian(self, params, unknowns):
        """ Jacobian for Sellar discipline 1"""
        J = {}

        J['y1','y2'] = -0.2
        J['y1','z'] = np.array([2*params['z'][0], 1.0])
        J['y1','x'] = 1.0

        return J


class SellarDis2(Component):
    """Component containing Discipline 2 -- no derivatives version."""

    def __init__(self):
        super(SellarDis2, self).__init__()

        # Global Design Variable
        self.add_param('z', val=np.zeros(2))

        # Coupling parameter
        self.add_param('y1', val=0.)

        # Coupling output
        self.add_output('y2', val=0.)

    def solve_nonlinear(self, params, unknowns, resids):
        """Evaluates the equation
        y2 = y1**(.5) + z1 + z2"""

        z1 = params['z'][0]
        z2 = params['z'][1]
        y1 = params['y1']

        # Note: this may cause some issues. However, y1 is constrained to be
        # above 3.16, so lets just let it converge, and the optimizer will
        # throw it out
        y1 = abs(y1)

        unknowns['y2'] = y1**.5 + z1 + z2


class SellarDis2withDerivatives(SellarDis2):
    """Component containing Discipline 2 -- derivatives version."""

    def jacobian(self, params, unknowns):
        """ Jacobian for Sellar discipline 2"""
        J = {}

        J['y2', 'y1'] = .5*params['y1']**-.5
        J['y2', 'z'] = np.ones(2)

        return J


class SellarNoDerivatives(Group):
    """ Group containing the Sellar MDA. This version uses the disciplines
    without derivatives."""

    def __init__(self):
        super(SellarNoDerivatives, self).__init__()

        self.add('d1', SellarDis1(), promotes=['*'])
        self.add('d2', SellarDis2(), promotes=['*'])

        self.add('px', ParamComp('x', 1.0), promotes=['*'])
        self.add('pz', ParamComp('z', np.array([5.0, 2.0])), promotes=['*'])


class SellarDerivatives(Group):
    """ Group containing the Sellar MDA. This version uses the disciplines
    with derivatives."""

    def __init__(self):
        super(SellarDerivatives, self).__init__()

        self.add('d1', SellarDis1withDerivatives(), promotes=['*'])
        self.add('d2', SellarDis2withDerivatives(), promotes=['*'])

        self.add('px', ParamComp('x', 1.0), promotes='*')
        self.add('pz', ParamComp('z', np.array([5.0, 2.0])), promotes='*')