from __future__ import division
import numpy
try:
    from petsc4py import PETSc
except:
    pass

import numbers
from six.moves import range

from openmdao.vectors.transfer import DefaultTransfer
from openmdao.vectors.transfer import PETScTransfer

real_types = tuple([numbers.Real, numpy.float32, numpy.float64])

class Vector(object):

    def __init__(self, name, typ, system, global_vector=None):
        self._name = name
        self._typ = typ

        self._assembler = system._sys_assembler
        self._system = system

        self._iproc = self._system.comm.rank + self._system._mpi_proc_range[0]
        self._initialize(global_vector)
        self._views, self._idxs = self._initialize_views()
        self._names = []

    def _create_subvector(self, system):
        return self.__class__(self._name, self._typ, system,
                              self._global_vector)

    def _clone(self):
        return self.__class__(self._name, self._typ, self._system,
                              self._global_vector)

    def __contains__(self, key):
        return key in self._names

    def __iter__(self):
        return iter(self._names)

    def __getitem__(self, key):
        return self._views[key][self._idxs[key]]

    def __setitem__(self, key, value):
        self._views[key][:] = value

    def _initialize(self):
        pass

    def _initialize_views(self):
        pass

    def __iadd__(self, vec):
        pass

    def __isub__(self, vec):
        pass

    def __imul__(self, val):
        pass

    def add_scal_vec(self, val, vec):
        pass

    def set_vec(self, vec):
        pass

    def set_const(self, val):
        pass

    def set_val(self, val):
        pass

    def get_norm(self):
        pass



class DefaultVector(Vector):

    TRANSFER = DefaultTransfer

    def _initialize(self, global_vector):
        if global_vector is None:
            self._global_vector = self
            self._data = self._create_data()
        else:
            self._global_vector = global_vector
            self._data = self._extract_data()

    def _create_data(self):
        return [numpy.zeros(numpy.sum(sizes[self._iproc, :]))
                   for sizes in self._assembler._variable_sizes[self._typ]]

    def _extract_data(self):
        variable_sizes = self._assembler._variable_sizes[self._typ]
        variable_set_indices = self._assembler._variable_set_indices[self._typ]

        ind1, ind2 = self._system._variable_allprocs_range[self._typ]
        sub_variable_set_indices = variable_set_indices[ind1:ind2, :]

        data = []
        for iset in range(len(variable_sizes)):
            bool_vector = sub_variable_set_indices[:, 0] == iset
            data_inds = sub_variable_set_indices[bool_vector, 1]
            if len(data_inds) > 0:
                sizes_array = variable_sizes[iset]
                ind1 = numpy.sum(sizes_array[self._iproc, :data_inds[0]])
                ind2 = numpy.sum(sizes_array[self._iproc, :data_inds[-1]+1])
                data.append(self._global_vector._data[iset][ind1:ind2])
            else:
                data.append(numpy.zeros(0))

        return data

    def _initialize_views(self):
        variable_sizes = self._assembler._variable_sizes[self._typ]
        variable_set_indices = self._assembler._variable_set_indices[self._typ]

        system = self._system
        variable_myproc_names = system._variable_myproc_names[self._typ]
        variable_myproc_indices = system._variable_myproc_indices[self._typ]
        meta = system._variable_myproc_metadata[self._typ]

        views = {}

        # contains a 0 index for floats or a slice(None) for arrays so getitem will
        # return either a float or a properly shaped array respectively.
        idxs = {}

        for ind, name in enumerate(variable_myproc_names):
            ivar_all = variable_myproc_indices[ind]
            iset, ivar = variable_set_indices[ivar_all, :]
            ind1 = numpy.sum(variable_sizes[iset][self._iproc, :ivar])
            ind2 = numpy.sum(variable_sizes[iset][self._iproc, :ivar+1])
            views[name] = self._global_vector._data[iset][ind1:ind2]
            views[name].shape = meta[ind]['shape']
            val = meta[ind]['value']
            if isinstance(val, real_types):
                idxs[name] = 0
            elif isinstance(val, numpy.ndarray):
                idxs[name] = slice(None)

        return views, idxs

    def __iadd__(self, vec):
        for iset in range(len(self._data)):
            self._data[iset] += vec._data[iset]
        return self

    def __isub__(self, vec):
        for iset in range(len(self._data)):
            self._data[iset] -= vec._data[iset]
        return self

    def __imul__(self, val):
        for data in self._data:
            data *= val
        return self

    def add_scal_vec(self, val, vec):
        for iset in range(len(self._data)):
            self._data[iset] *= val * vec._data[iset]

    def set_vec(self, vec):
        for iset in range(len(self._data)):
            self._data[iset][:] = vec._data[iset]

    def set_const(self, val):
        for data in self._data:
            data[:] = val

    def get_norm(self):
        global_sum = 0
        for data in self._data:
            global_sum += numpy.sum(data**2)
        return global_sum ** 0.5



class PETScVector(DefaultVector):

    TRANSFER = PETScTransfer

    def _initialize(self, global_vector):
        if global_vector is None:
            self._global_vector = self
            self._data = self._create_data()
        else:
            self._global_vector = global_vector
            self._data = self._extract_data()

        self._petsc = []
        for iset in range(len(self._data)):
            petsc = PETSc.Vec().createWithArray(self._data[iset][:],
                                                comm=self._system.comm)
            self._petsc.append(petsc)

    def get_norm(self):
        global_sum = 0
        for iset in range(len(self._data)):
            global_sum += numpy.sum(self._data[iset]**2)
        return self._system.comm.allreduce(global_sum) ** 0.5
