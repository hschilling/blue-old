"""Define the base System class."""
from __future__ import division

from fnmatch import fnmatchcase

import numpy

from six import iteritems
from six.moves import range

from openmdao.proc_allocators.proc_allocator import DefaultProcAllocator
from openmdao.solvers.solver import NonlinearBlockGS
from openmdao.jacobians.jacobian import DefaultJacobian



class System(object):
    """Base class for all systems in OpenMDAO.

    Never instantiated; subclassed by Group or Component.
    All subclasses have their attributes defined here.

    Attributes
    ----------
    name : str
        name of the system, must be different from siblings.
    path_name : str
        global name of the system, including the path.
    comm : MPI.Comm or FakeComm
        MPI communicator object.

    args : list of objects
        user-defined arguments (to be used in apply_nonlinear, ...).
    kwargs : dict of objects
        dictionary of user-defined arguments.
    global_kwargs : dict of objects
        self.kwargs combined with kwargs of parent systems.

    _sys_depth : int
        distance from the root node in the hierarchy tree.
    _sys_assembler: Assembler
        pointer to the global assembler object.

    _mpi_proc_allocator : ProcAllocator
        object that distributes procs among subsystems.
    _mpi_proc_range : [int, int]
        indices of procs owned by comm with respect to COMM_WORLD.

    _subsystems_allprocs : [System, ...]
        list of all subsystems (children of this system).
    _subsystems_myproc : [System, ...]
        list of local subsystems that exist on this proc.
    _subsystems_inds : [int, ...]
        list of indices of subsystems on this proc among all subsystems.

    _variable_allprocs_names : {'input': [str, ...], 'output': [str, ...]}
        list of names of all owned variables, not just on current proc.
    _variable_allprocs_range : {'input': [int, int], 'output': [int, int]}
        index range of owned variables with respect to all problem variables.
    _variable_allprocs_indices : {'input': dict, 'output': dict}
        dictionary of global indices keyed by the variable name.

    _variable_myproc_names : {'input': [str, ...], 'output': [str, ...]}
        list of names of owned variables on current proc.
    _variable_myproc_metadata : {'input': list, 'output': list}
        list of metadata dictionaries of variables that exist on this proc.
    _variable_myproc_indices : {'input': ndarray[:], 'output': ndarray[:]}
        integer arrays of global indices of variables on this proc.

    _variable_maps : {'input': dict, 'output': dict}
        dictionary of variable names and their aliases (for promotes/renames).
    _variable_promotes : { 'any': set(), 'input': set(), 'output': set() }
        dictionary of sets of variable names/wildcards specifying promotion
        (used to calculate _variable_maps)
    _variable_renames : { 'input': {}, 'output': {} }
        dictionary of mappings used to specify variables to be renamed in the
        parent group. (used to calculate _variable_maps)

    _variable_connections : dict
        dictionary of input:output connections between subsystems.
    _variable_connections_indices : [(int, int), ...]
        _variable_connections with variable indices instead of names.

    _vectors : {'input': dict, 'output': dict, 'residual': dict}
        dict of vector objects.
    _vector_transfers : dict
        dict of transfer objects.
    _vector_var_ids : dict
        dictionary of index arrays of relevant variables for this vector

    _inputs : Vector
        inputs vector; points to _vectors['input'][None].
    _outputs : Vector
        outputs vector; points to _vectors['output'][None].
    _residuals : Vector
        residuals vector; points to _vectors['residual'][None].
    _transfers : dict of Transfer
        transfer object; points to _vector_transfers[None].

    _jacobian : Jacobian
        global Jacobian object to be used in apply_linear

    _solvers_nonlinear : NonlinearSolver
        nonlinear solver to be used for solve_nonlinear.
    _solvers_linear : LinearSolver
        linear solver to be used for solve_linear; not the Newton system.
    _solvers_print : boolean
        global overriding flag that turns off all solver output if 'False'.
    """

    def __init__(self, **kwargs):
        """Initialize all attributes.

        All subclasses use this __init__ method without overriding it.

        Args
        ----

        **kwargs: dict of keyword arguments
            available here and in all descendants of this system.
        """
        self.name = ''
        self.path_name = ''
        self.comm = None

        self.kwargs = kwargs
        self.global_kwargs = {}

        self._sys_depth = 0
        self._sys_assembler = None

        self._mpi_proc_allocator = DefaultProcAllocator()
        self._mpi_proc_range = [0, 1]

        self._subsystems_allprocs = []
        self._subsystems_myproc = []
        self._subsystems_inds = []

        self._variable_allprocs_names = {'input': [], 'output': []}
        self._variable_allprocs_range = {'input': [0, 0], 'output': [0, 0]}
        self._variable_allprocs_indices = {'input': {}, 'output': {}}

        self._variable_myproc_names = {'input': [], 'output': []}
        self._variable_myproc_metadata = {'input': [], 'output': []}
        self._variable_myproc_indices = {'input': None, 'output': None}

        self._variable_maps = {'input': {}, 'output': {}}
        self._variable_promotes = {'any': set(), 'input': set(), 'output': set()}
        self._variable_renames = {'input': {}, 'output': {}}

        self._variable_connections = {}
        self._variable_connections_indices = []

        self._vectors = {'input': {}, 'output': {}, 'residual': {}}
        self._vector_transfers = {}
        self._vector_var_ids = {}

        self._inputs = None
        self._outputs = None
        self._residuals = None
        self._transfers = None

        self._jacobian = DefaultJacobian()

        self._solvers_nonlinear = NonlinearBlockGS()
        self._solvers_linear = NonlinearBlockGS() # temporary hack!
        self._solvers_print = True

        self.initialize()

    def _setup_processors(self, path, comm, global_kwargs,
                          depth, assembler, proc_range):
        """Recursively split comms and define local subsystems.

        Sets the following attributes:
            path_name
            comm
            global_kwargs
            _sys_depth
            _sys_assembler
            _mpi_proc_range
            _subsystems_myproc
            _subsystems_inds

        Args
        ----
        path : str
            parent names to prepend to name to get the pathname
        comm : MPI.Comm or FakeComm
            communicator for this system (already split, if applicable).
        global_kwargs : dict
            dictionary with kwargs of all parents assembled in it.
        depth : int
            depth level for this system - i.e., distance from root node.
        assembler : Assembler
            pointer to the global assember object to distribute to everyone.
        proc_range : [int, int]
            indices of procs owned by comm with respect to COMM_WORLD.
        """
        # Set attributes
        self.path_name = '.'.join((path, self.name)) if path else self.name
        self.comm = comm
        self.global_kwargs = global_kwargs
        self._sys_depth = depth
        self._sys_assembler = assembler
        self._mpi_proc_range = proc_range

        # Add self's kwargs to dictionary of parents' kwargs (already new copy)
        self.global_kwargs.update(self.kwargs)

        # Optional user-defined method
        self.initialize_processors()

        nsub = len(self._subsystems_allprocs)
        # If this is a group:
        if nsub > 0:
            # Call the load balancing algorithm
            tmp = self._mpi_proc_allocator(nsub, comm, proc_range)
            sub_inds, sub_comm, sub_proc_range = tmp

            # Define local subsystems
            self._subsystems_myproc = [self._subsystems_allprocs[ind]
                                       for ind in sub_inds]
            self._subsystems_inds = sub_inds

            # Perform recursion
            for subsys in self._subsystems_myproc:
                sub_global_kwargs = self.global_kwargs.copy()
                subsys._setup_processors(self.path_name, sub_comm,
                                         sub_global_kwargs, depth+1, assembler,
                                         sub_proc_range)

    def _setup_variables(self, recursion=True):
        """Assemble variable metadata and names lists.

        Sets the following attributes:
            _variable_allprocs_names
            _variable_myproc_names
            _variable_myproc_metadata

        Args
        ----
        recursion : boolean
            recursion is not performed if traversing up the tree after reconf.
        """
        # Perform recursion
        if recursion:
            for subsys in self._subsystems_myproc:
                subsys._setup_variables()

        # Empty the lists in case this is part of a reconfiguration
        for typ in ['input', 'output']:
            self._variable_allprocs_names[typ] = []
            self._variable_myproc_names[typ] = []
            self._variable_myproc_metadata[typ] = []

        # If this is a component, the user calls add_input/add_output
        if len(self._subsystems_allprocs) == 0:
            self.initialize_variables()
        # If this is a group, assemble the metadata and names lists
        else:
            for typ in ['input', 'output']:
                for subsys in self._subsystems_myproc:
                    # Assemble the names list from subsystems
                    subsys._variable_maps[typ] = subsys._get_maps(typ)
                    for sub_name in subsys._variable_allprocs_names[typ]:
                        name = subsys._variable_maps[typ][sub_name]
                        self._variable_allprocs_names[typ].append(name)
                        self._variable_myproc_names[typ].append(name)

                    # Assemble the metadata list from the subsystems
                    metadata = subsys._variable_myproc_metadata[typ]
                    self._variable_myproc_metadata[typ].extend(metadata)

                # The names list is on all procs, allgather all names
                if self.comm.size > 1:

                    # One representative proc from each sub_comm adds names
                    sub_comm = self._subsystems_myproc[0].comm
                    if sub_comm.rank == 0:
                        names = self._variable_allprocs_names[typ]
                    else:
                        names = []

                    # Every proc on this comm now has global variable names
                    raw = self.comm.allgather(names)
                    self._variable_allprocs_names[typ] = []
                    for names in raw:
                        self._variable_allprocs_names[typ].extend(names)

    def _setup_variable_indices(self, index, recursion=True):
        """Define the variable indices and range.

        Sets the following attributes:
            _variable_allprocs_range
            _variable_allprocs_indices
            _variable_myproc_indices

        Args
        ----
        index : {'input': int, 'output': int}
            current global variable counter.
        recursion : boolean
            recursion is not performed if traversing up the tree after reconf.
        """
        # Define the global variable range for the system
        for typ in ['input', 'output']:
            size = len(self._variable_allprocs_names[typ])
            self._variable_allprocs_range[typ][0] = index[typ]
            self._variable_allprocs_range[typ][1] = index[typ] + size

        # If group, compute _variable_myproc_indices as follows
        if len(self._subsystems_myproc) > 0:
            subsys0 = self._subsystems_myproc[0]

            # Pre-recursion: compute 'index' to pass to subsystems
            # Need offset: number of variables on procs before current proc
            # Necessary because of multiple global counters on different procs
            if self.comm.size > 1:
                for typ in ['input', 'output']:
                    # Compute the variable count list; 0 on rank > 0 procs
                    sub_comm = self._subsystems_myproc[0].comm
                    if sub_comm.rank == 0:
                        nvar_myproc = len(subsys0._variable_allprocs_names[typ])
                    else:
                        nvar_myproc = 0
                    nvar_allprocs = self.comm.allgather(nvar_myproc)

                    # Compute the offset
                    iproc = self.comm.rank
                    nvar_myproc = len(subsys0._variable_allprocs_names[typ])
                    index[typ] += numpy.sum(nvar_allprocs[:iproc+1]) \
                               - nvar_myproc

            # Perform the recursion
            if recursion:
                for subsys in self._subsystems_myproc:
                    subsys._setup_variable_indices(index)

            # Post-recursion: assemble local variable indices from subsystems
            for typ in ['input', 'output']:
                raw = []
                for subsys in self._subsystems_myproc:
                    raw.append(subsys._variable_myproc_indices[typ])
                self._variable_myproc_indices[typ] = numpy.concatenate(raw)

        # If component, _variable_myproc_indices is simply an arange
        else:
            for typ in ['input', 'output']:
                ind1, ind2 = self._variable_allprocs_range[typ]
                self._variable_myproc_indices[typ] = numpy.arange(ind1, ind2)

        # Reset index dict to the global variable count on all procs
        # Necessary for younger siblings to have proper index values
        for typ in ['input', 'output']:
            index[typ] = self._variable_allprocs_range[typ][1]

        # Populate the _variable_allprocs_indices dictionary
        for typ in ['input', 'output']:
            for ind in range(len(self._variable_allprocs_names[typ])):
                name = self._variable_allprocs_names[typ][ind]
                ivar_all = self._variable_allprocs_range[typ][0] + ind
                self._variable_allprocs_indices[typ][name] = ivar_all

    def _setup_connections(self):
        """Recursively assemble a list of input-output connections.

        Sets the following attributes:
            _variable_connections_indices
        """
        # Perform recursion and assemble pairs from subsystems
        pairs = []
        for subsys in self._subsystems_myproc:
            subsys._setup_connections()
            if subsys.comm.rank == 0:
                pairs.extend(subsys._variable_connections_indices)

        # Do an allgather to gather from root procs of all subsystems
        if self.comm.size > 1:
            pairs_raw = self.comm.allgather(pairs)
            pairs = []
            for sub_pairs in pairs_raw:
                pairs.extend(sub_pairs)

        # Loop through user-defined connections
        var_allprocs_names = self._variable_allprocs_names
        for ip_name, (op_name, src_indices) in iteritems(self._variable_connections):

            if ip_name in var_allprocs_names['input'] and op_name in var_allprocs_names['output']:
                ip_index = var_allprocs_names['input'].index(ip_name)
                op_index = var_allprocs_names['output'].index(op_name)
                ip_index += self._variable_allprocs_range['input'][0]
                op_index += self._variable_allprocs_range['output'][0]
                pairs.append([ip_index, op_index])

                if src_indices is not None:
                    # set the 'indices' metadata in the input variable
                    try:
                        ip_myproc_index = self._variable_myproc_names['input'].index(ip_name)
                    except ValueError:
                        pass
                    else:
                        meta = self._variable_myproc_metadata['input'][ip_myproc_index]
                        meta['indices'] = numpy.array(src_indices, dtype=int)
                        meta['shape'] = meta['indices'].shape

        self._variable_connections_indices = pairs

    def _setup_vector(self, vectors, vector_var_ids):
        """Add this vector and assign sub_vectors to subsystems.

        Sets the following attributes:
            _vectors
            _vector_transfers
            _inputs*
            _outputs*
            _residuals*
            _transfers*

        * If vec_name is None - i.e., we are setting up the nonlinear vector

        Args
        ----
        vectors : {'input': Vector, 'output': Vector, 'residual': Vector}
            Vector objects corresponding to 'name'.
        vector_var_ids : ndarray[:]
            integer array of all relevant variables for this vector.
        """
        vec_name = vectors['output']._name

        # Set the incoming _vectors in the appropriate attribute
        for key in ['input', 'output', 'residual']:
            self._vectors[key][vec_name] = vectors[key]

        # Compute the transfer for this vector set
        self._vector_transfers[vec_name] = self._get_transfers(vectors)

        # Assign relevant variables IDs array
        self._vector_var_ids[vec_name] = vector_var_ids

        # Define shortcuts for convenience
        if vec_name is None:
            self._inputs = self._vectors['input'][None]
            self._outputs = self._vectors['output'][None]
            self._residuals = self._vectors['residual'][None]
            self._transfers = self._vector_transfers[None]

        # Perform recursion
        for subsys in self._subsystems_myproc:

            sub_vectors = {}
            for key in ['input', 'output', 'residual']:
                sub_vectors[key] = vectors[key]._create_subvector(subsys)

            subsys._setup_vector(sub_vectors, vector_var_ids)

    def _setup_solvers(self):
        """Recursively set up all solvers in this and systems below."""
        self._solvers_nonlinear._setup_solvers(self, 0)
        self._solvers_linear._setup_solvers(self, 0)
        for subsys in self._subsystems_myproc:
            subsys._setup_solvers()

    def _get_transfers(self, vectors):
        """Compute transfers.

        Args
        ----
        vectors : {'input': Vector, 'output': Vector, 'residual': Vector}
            dictionary of Vector objects

        Returns
        -------
        dict of Transfer
            dictionary of full and partial Transfer objects.
        """
        Transfer = vectors['output'].TRANSFER

        nsub_allprocs = len(self._subsystems_allprocs)
        var_range = self._variable_allprocs_range
        subsystems_myproc = self._subsystems_myproc
        subsystems_inds = self._subsystems_inds

        # Call the assembler's transfer setup routine
        compute_transfers = self._sys_assembler._compute_transfers
        xfer_indices = compute_transfers(nsub_allprocs, var_range,
                                         subsystems_myproc, subsystems_inds)
        [xfer_ip_inds, xfer_op_inds,
         fwd_xfer_ip_inds, fwd_xfer_op_inds,
         rev_xfer_ip_inds, rev_xfer_op_inds] = xfer_indices

        # Create Transfer objects from the raw indices
        transfers = {}
        transfers[None] = Transfer(vectors['input'],
                                   vectors['output'],
                                   xfer_ip_inds,
                                   xfer_op_inds,
                                   self.comm)
        for isub in range(len(fwd_xfer_ip_inds)):
            transfers['fwd', isub] = Transfer(vectors['input'],
                                              vectors['output'],
                                              fwd_xfer_ip_inds[isub],
                                              fwd_xfer_op_inds[isub],
                                              self.comm)
        for isub in range(len(rev_xfer_ip_inds)):
            transfers['rev', isub] = Transfer(vectors['input'],
                                              vectors['output'],
                                              rev_xfer_ip_inds[isub],
                                              rev_xfer_op_inds[isub],
                                              self.comm)
        return transfers

    def _get_maps(self, typ):
        """Define variable maps based on promotes and renames lists.

        Args
        ----
        typ : str
            Either 'input' or 'output'.
        """
        maps = {}

        gname = self.name + '.' if self.name else ''

        promotes = self._variable_promotes['any']
        promotes_typ = self._variable_promotes[typ]
        renames = self._variable_renames[typ]

        if promotes:
            names = promotes
            patterns = [n for n in names if '*' in n or '?' in n]
        elif promotes_typ:
            names = promotes_typ
            patterns = [n for n in names if '*' in n or '?' in n]
        else:
            names = ()
            patterns = ()

        for name in self._variable_allprocs_names[typ]:
            if name in names:
                maps[name] = name
                continue

            for pattern in patterns:
                # if name matches, promote that variable to parent
                if fnmatchcase(name, pattern):
                    maps[name] = name
                    break
            else:
                if name in renames:
                    # Rename selected variables to custom names in the parent system
                    maps[name] = renames[name]
                else:
                    # Default: the parent system's name is prepended to variable name
                    maps[name] = gname + name if gname else name

        return maps

    def _get_vectors(self, vec_name, var_ind_range, mode):
        d_inputs = self._vectors['input'][vec_name]
        d_outputs = self._vectors['output'][vec_name]
        d_residuals = self._vectors['residual'][vec_name]

        if mode == 'fwd':
            d_residuals.set_const(0.0)
        elif mode == 'rev':
            d_inputs.set_const(0.0)
            d_outputs.set_const(0.0)

        op_names = []
        op_ind = self._variable_allprocs_range['output'][0]
        for op_name in self._variable_allprocs_names['output']:
            if op_ind in self._vector_var_ids[vec_name]:
                op_names.append(op_name)
            op_ind += 1

        ip_names = []
        ip_ind = self._variable_allprocs_range['input'][0]
        for ip_name in self._variable_allprocs_names['input']:
            input_var_id = self._sys_assembler._input_var_ids[ip_ind]
            valid = var_ind_range[0] <= ip_ind < var_ind_range[1]
            valid = valid and input_var_id in self._vector_var_ids[vec_name]
            if valid:
                ip_names.append(ip_name)
            ip_ind += 1

        d_inputs._names = set(ip_names)
        d_outputs._names = set(op_names)

        return d_inputs, d_outputs, d_residuals

    def get_subsystem(self, name):
        """Return the system called 'name' in the current namespace.

        Args
        ----
        name : str
            name of the desired system in the current namespace.

        Returns
        -------
        System or None
            System if found on this proc else None.
        """
        if name == self.path_name:
            # If this system's name matches, target found
            return self
        else:
            for subsys in self._subsystems_myproc:
                result = subsys.get_subsystem(name)
                if result is not None:
                    return result
            return None

    def set_solver_print(self, flag):
        """Recursively set solver print flag for this and all systems below.

        Args
        ----
        flag : boolean
            if False, solver printing is surpressed for this system and below.
        """
        self._solvers_print = flag
        for subsys in self._subsystems_myproc:
            subsys.set_solver_print(flag)

    def set_jacobian(self, jacobian=None, is_top=True):
        """Recursively set the system's jacobian attribute.

        Args
        ----
        jacobian : Jacobian or None
            Jacobian object to be set; if None, reset to the DefaultJacobian.
        is_top : boolean
            whether this is the top; i.e., start of the recursion
        """
        if jacobian is None:
            self._jacobian = DefaultJacobian()
        else:
            self._jacobian = jacobian
            if is_top:
                self._jacobian._top_name = self.path_name
                self._jacobian._top_system = self
                self._jacobian._assembler = self._sys_assembler

        for subsys in self._subsystems_myproc:
            subsys.set_jacobian(jacobian, False)

    def initialize(self):
        """Optional user-defined method run once during instantiation.

        Available attributes:
            name
            args
            kwargs
        """
        pass

    def initialize_processors(self):
        """Optional user-defined method run after repartitioning/rebalancing.

        Available attributes:
            name
            path_name
            comm
            args
            kwargs
            global_kwargs
        """
        pass

    def initialize_variables(self):
        """Required method for components to declare inputs and outputs.

        Available attributes:
            name
            path_name
            comm
            args
            kwargs
            global_kwargs
        """
        pass
