"""Define the base Vector and Transfer classes."""
from __future__ import division, print_function
import numpy
from six.moves import range
class Vector(object):
    """Base Vector class.

    This class is instantiated for inputs, outputs, and residuals.
    It provides a dictionary interface and an arithmetic operations interface.
    Implementations:
    
    - <DefaultVector>
    - <PETScVector>

    Attributes
    ----------
    _name : str
        right-hand-side (RHS) name.
    _typ : str
        'input' or 'output'.
    _assembler : Assembler
        pointer to the assembler.
    _system : System
        pointer to the owning system.
    _iproc : int
        global processor index.
    _views : dict
        dictionary mapping variable names to the ndarray views.
    _views_flat : dict
        dictionary mapping variable names to the flattened ndarray views.
    _idxs : dict
        0 or slice(None), used so that 1-sized vectors are made floats.
    _names : set([str, ...])
        set of variables that are relevant in the current context.
    _global_vector : Vector
        pointer to the vector owned by the root system.
    _data : list
        list of the actual allocated data (depends on implementation).
    _indices : list
        list of indices mapping the varset-grouped data to the global vector.

    """
    def __init__(self, name, typ, system, global_vector=None):
        """Initialize all attributes.

        Args
        ----
        name : str
            right-hand-side (RHS) name.
        typ : str
            'input' for input vectors; 'output' for output/residual vectors.
        system : <System>
            pointer to the owning system.
        global_vector : <Vector>
            pointer to the vector owned by the root system.

        """
        self._name = name
        self._typ = typ
        self._assembler = system._sys_assembler
        self._system = system
        self._iproc = self._system.comm.rank + self._system._mpi_proc_range[0]
        self._views = {}
        self._views_flat = {}
        self._idxs = {}
        # self._names will either be equivalent to self._views or to the
        # set of variables relevant to the current matvec product.
        self._names = self._views
        self._global_vector = None
        self._data = []
        self._indices = []
        if global_vector is None:
            self._global_vector = self
        else:
            self._global_vector = global_vector
        self._initialize_data(global_vector)
        self._initialize_views()
    def _create_subvector(self, system):
        """Return a smaller vector for a subsystem.

        Args
        ----
        system : <System>
            system for the subvector that is a subsystem of self._system.

        Returns
        -------
        <Vector>
            subvector instance.

        """
        return self.__class__(self._name, self._typ, system,
                              self._global_vector)
    def _clone(self):
        """Return a copy that does not provide view access to its data.

        Returns
        -------
        Vector
            instance of the clone; the data is copied.
        """
        vec = self.__class__(self._name, self._typ, self._system,
                             self._global_vector)
        vec._clone_data()
        return vec
    def get_data(self, array=None):
        """Get the array combining the data of all the varsets.

        Args
        ----
        array : ndarray or None
            Array to fill in with the values; otherwise new array created.

        Returns
        -------
        ndarray
            Array combining the data of all the varsets.

        """
        if array is None:
            inds = self._system._variable_myproc_indices[self._typ]
            sizes = self._assembler._variable_sizes_all[self._typ][self._iproc,
                                                                   inds]
            array = numpy.zeros(numpy.sum(sizes))
        for ind, data in enumerate(self._data):
            array[self._indices[ind]] = data
        return array
    def set_data(self, array):
        """Set the incoming array combining the data of all the varsets.

        Args
        ----
        array : ndarray
            Array to set to the data for all the varsets.

        """
        for ind, data in enumerate(self._data):
            data[:] = array[self._indices[ind]]
    def iadd_data(self, array):
        """In-place add the incoming combined array.

        Args
        ----
        array : ndarray
            Array to set to the data for all the varsets.

        """
        for ind, data in enumerate(self._data):
            data[:] += array[self._indices[ind]]
    def __contains__(self, key):
        """Check if the variable is involved in the current mat-vec product.

        Args
        ----
        key : str
            variable name in the owning system's namespace.

        Returns
        -------
        boolean
            True or False.

        """
        return key in self._names
    def __iter__(self):
        """Iterator over variables involved in the current mat-vec product.

        Returns
        -------
        listiterator
            iterator over the variable names.

        """
        return iter(self._names)
    def __getitem__(self, key):
        """Get the unscaled variable value in true units.

        Args
        ----
        key : str
            variable name in the owning system's namespace.

        Returns
        -------
        float or ndarray
            variable value (not scaled, not dimensionless).

        """
        if key in self._names:
            return self._views[key][self._idxs[key]]
        else:
            raise KeyError("Variable '%s' not found." % key)
    def __setitem__(self, key, value):
        if key in self._names:
            self._views[key][:] = value
        else:
            raise KeyError("Variable '%s' not found." % key)
    def _initialize_data(self, global_vector):
        """Internally allocate vectors.
        Must be implemented by the subclass.
        Sets the following attributes:

        - _data

        Args
        ----
        global_vector : Vector or None
            the root's vector instance or None, if we are at the root.

        """
        pass
    def _initialize_views(self):
        """Internally assemble views onto the vectors.
        Must be implemented by the subclass.
        Sets the following attributes:

        - _views
        - _views_flat
        - _idxs

        """
        pass
    def _clone_data(self):
        """For each item in _data, replace it with a copy of the data.
        Must be implemented by the subclass.
        """
        pass
    def __iadd__(self, vec):
        """Perform in-place vector addition.
        Must be implemented by the subclass.

        Args
        ----
        vec : <Vector>
            vector to add to self.

        """
        pass
    def __isub__(self, vec):
        """Perform in-place vector substraction.
        Must be implemented by the subclass.

        Args
        ----
        vec : <Vector>
            vector to subtract from self.

        """
        pass
    def __imul__(self, val):
        """Perform in-place scalar multiplication.
        Must be implemented by the subclass.

        Args
        ----
        val : int or float
            scalar to multiply self.

        """
        pass
    def add_scal_vec(self, val, vec):
        """Perform in-place addition of a vector times a scalar.
        Must be implemented by the subclass.

        Args
        ----
        val : int or float
            scalar.
        vec : <Vector>
            this vector times val is added to self.

        """
        pass
    def set_vec(self, vec):
        """Set the value of this vector to that of the incoming vector.
        Must be implemented by the subclass.

        Args
        ----
        vec : <Vector>
            the vector whose values self is set to.

        """
        pass
    def set_const(self, val):
        """Set the value of this vector to a constant scalar value.
        Must be implemented by the subclass.

        Args
        ----
        val : int or float
            scalar to set self to.

        """
        pass
    def get_norm(self):
        """Return the norm of this vector.
        Must be implemented by the subclass.

        Returns
        -------
        float
            norm of this vector.

        """
        pass
class Transfer(object):
    """Base Transfer class.

    Implementations:

    - <DefaultTransfer>
    - <PETScTransfer>

    Attributes
    ----------
    _ip_vec : Vector
        pointer to the input vector.
    _op_vec : Vector
        pointer to the output vector.
    _ip_inds : int ndarray
        input indices for the transfer.
    _op_inds : int ndarray
        output indices for the transfer.
    _comm : MPI.Comm or FakeComm
        communicator of the system that owns this transfer.

    """
    def __init__(self, ip_vec, op_vec, ip_inds, op_inds, comm):
        """Initialize all attributes.

        Args
        ----
        ip_vec : <Vector>
            pointer to the input vector.
        op_vec : <Vector>
            pointer to the output vector.
        ip_inds : int ndarray
            input indices for the transfer.
        op_inds : int ndarray
            output indices for the transfer.
        comm : MPI.Comm or <FakeComm>
            communicator of the system that owns this transfer.

        """
        self._ip_vec = ip_vec
        self._op_vec = op_vec
        self._ip_inds = ip_inds
        self._op_inds = op_inds
        self._comm = comm
        self._initialize_transfer()
    def _initialize_transfer(self):
        """Set up the transfer; do any necessary pre-computation.
        Optionally implemented by the subclass.
        """
        pass
    def __call__(self, ip_vec, op_vec, mode='fwd'):
        """Perform transfer.
        Must be implemented by the subclass.

        Args
        ----
        ip_vec : <Vector>
            pointer to the input vector.
        op_vec : <Vector>
            pointer to the output vector.
        mode : str
            'fwd' or 'rev'.
            
        """
        pass
