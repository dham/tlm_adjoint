#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright(c) 2018 The University of Edinburgh
#
# This file is part of tlm_adjoint.
# 
# tlm_adjoint is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, version 3 of the License.
# 
# tlm_adjoint is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public License
# along with tlm_adjoint.  If not, see <https://www.gnu.org/licenses/>.

from .backend import *

import copy
from collections import OrderedDict
import ufl

__all__ = \
  [
    "AssemblyCache",
    "Cache",
    "CacheException",
    "CacheIndex",
    "Constant",
    "DirichletBC",
    "Function",
    "LinearSolverCache",
    "ReplacementFunction",
    "assembly_cache",
    "is_homogeneous_bcs",
    "is_static",
    "is_static_bcs",
    "linear_solver_cache",
    "new_count",
    "replaced_form",
    "replaced_function",
    "set_assembly_cache",
    "set_linear_solver_cache",
  ]

class CacheException(Exception):
  pass
  
class Constant(backend_Constant):
  def __init__(self, *args, **kwargs):
    kwargs = copy.copy(kwargs)
    static = kwargs.pop("static", False)
    
    backend_Constant.__init__(self, *args, **kwargs)
    self.__static = static
  
  def is_static(self):
    return self.__static
  
class Function(backend_Function):
  def __init__(self, *args, **kwargs):
    kwargs = copy.copy(kwargs)
    static = kwargs.pop("static", False)
    
    backend_Function.__init__(self, *args, **kwargs)
    self.__static = static
  
  def is_static(self):
    return self.__static

class DirichletBC(backend_DirichletBC):
  def __init__(self, *args, **kwargs):      
    kwargs = copy.copy(kwargs)
    static = kwargs.pop("static", False)
    homogeneous = kwargs.pop("homogeneous", False)
    
    backend_DirichletBC.__init__(self, *args, **kwargs)    
    self.__static = static
    self.__homogeneous = homogeneous
  
  def is_static(self):
    return self.__static
  
  def is_homogeneous(self):
    return self.__homogeneous
  
  def homogenize(self):
    if not self.__homogeneous:
      backend_DirichletBC.homogenize(self)
      self.__homogeneous = True

def is_static(expr):
  for c in ufl.algorithms.extract_coefficients(expr):
    if not hasattr(c, "is_static") or not c.is_static():
      return False
  return True

def is_static_bcs(bcs):
  for bc in bcs:
    if not hasattr(bc, "is_static") or not bc.is_static():
      return False
  return True

def is_homogeneous_bcs(bcs):
  for bc in bcs:
    if not hasattr(bc, "is_homogeneous") or not bc.is_homogeneous():
      return False
  return True
  
def parameters_key(parameters):
  key = []
  for name in sorted(parameters.keys()):
    sub_parameters = parameters[name]
    if isinstance(sub_parameters, (Parameters, dict)):
      key.append((name, parameters_key(sub_parameters)))
    elif isinstance(sub_parameters, list):
      key.append((name, tuple(sub_parameters)))
    else:
      key.append((name, sub_parameters))
  return tuple(key)
  
class CacheIndex:
  def __init__(self, index = None):
    self._index = index
  
  def clear(self):
    self.set_index(None)
  
  def index(self):
    return self._index
  
  def set_index(self, index):
    self._index = index

class Cache:
  def __init__(self):
    self._keys = OrderedDict()
    self._cache = []
  
  def __getitem__(self, key):
    return self._cache[key.index()]
  
  def clear(self):
    for value in self._keys.values():
      value.clear()
    self._keys.clear()
    self._cache.clear()
  
  def append(self, key, value):
    self._cache.append(value)
    index = CacheIndex(len(self._cache) - 1)
    self._keys[key] = index
    return index

def new_count():
  return Constant(0).count()
  
class ReplacementFunction(ufl.classes.Coefficient):
  def __init__(self, x):
    ufl.classes.Coefficient.__init__(self, x.function_space(), count = new_count())
    self.__space = x.function_space()
    self.__id = x.id()
    self.__name = x.name()
    self.__static = is_static(x)
  
  def function_space(self):
    return self.__space
  
  def id(self):
    return self.__id
  
  def name(self):
    return self.__name
  
  def is_static(self):
    return self.__static

def replaced_function(x):
  if isinstance(x, ReplacementFunction):
    return x
  if not hasattr(x, "_tlm_adjoint__ReplacementFunction"):
    x._tlm_adjoint__ReplacementFunction = ReplacementFunction(x)
  return x._tlm_adjoint__ReplacementFunction

def replaced_form(form):
  replace_map = OrderedDict()
  for c in form.coefficients():
    if isinstance(c, backend_Function):
      replace_map[c] = replaced_function(c)
  return ufl.replace(form, replace_map)

def form_key(form):
  return ufl.algorithms.expand_indices(ufl.algorithms.expand_compounds(ufl.algorithms.expand_derivatives(replaced_form(form))))

def assemble_key(form, bcs, form_compiler_parameters):  
  return (form_key(form), tuple(bcs), parameters_key(form_compiler_parameters))

class AssemblyCache(Cache):
  def assemble(self, form, bcs = [], form_compiler_parameters = {}):  
    key = assemble_key(form, bcs, form_compiler_parameters)
    index = self._keys.get(key, None)
    if index is None:
      rank = len(form.arguments())
      if rank == 0:
        if len(bcs) > 0:
          raise CacheException("Unexpected boundary conditions for rank 0 form")
        b = assemble(form, form_compiler_parameters = form_compiler_parameters)
      elif rank == 1:
        b = assemble(form, form_compiler_parameters = form_compiler_parameters)
        for bc in bcs:
          bc.apply(b)
      elif rank == 2:
        b = assemble(form, form_compiler_parameters = form_compiler_parameters)
        for bc in bcs:
          bc.apply(b)
        b.force_evaluation()
      else:
        raise CacheException("Unexpected form rank %i" % rank)
      index = self.append(key, b)
    else:
      b = self[index]
      
    return index, b

def linear_solver_key(form, bcs, linear_solver_parameters, form_compiler_parameters):
  return (form_key(form), tuple(bcs), parameters_key(linear_solver_parameters), parameters_key(form_compiler_parameters))

class LinearSolverCache(Cache):
  def linear_solver(self, form, A, bcs = [], linear_solver_parameters = {}, form_compiler_parameters = {}):
    key = linear_solver_key(form, bcs, linear_solver_parameters, form_compiler_parameters)
    index = self._keys.get(key, None)
    if index is None:
      solver = LinearSolver(A, solver_parameters = linear_solver_parameters)
      index = self.append(key, solver)
    else:
      solver = self[index]

    return index, solver

_caches = [AssemblyCache(), LinearSolverCache()]
def assembly_cache():
  return _caches[0]
def set_assembly_cache(assembly_cache):
  _caches[0] = assembly_cache
def linear_solver_cache():
  return _caches[1]
def set_linear_solver_cache(linear_solver_cache):
  _caches[1] = linear_solver_cache