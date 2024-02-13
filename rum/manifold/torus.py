import numpy as np
from .manifold import Manifold, GlobalChartAtlas

class TorusManifold(Manifold):
  def __init__(self, dim, sampler):
    assert dim == 2 # TODO.
    super(TorusManifold, self).__init__(dim, dim + 1)

    self.sampler = sampler

    self.R = 2.0 / 3.0 # Radius of "inside" circle around 1-d hole. 
    self.r = 1.0 / 3.0 # Radius of "outside" circle around 2-d hole.

    self.atlas = GlobalChartAtlas(
      self.map,
      self.inverse_map,
      self.norm,
      None, # TODO.
      None # TODO.
    )

  def retraction(self, p, v):
    v = self.normalize(p, v)
    xi = self.map(p)
    xi += v
    standardize = lambda x : (x + 2 * np.pi) % (2 * np.pi)
    xi = standardize(xi) 
    return self.inverse_map(xi)

  def starting_state(self):
    #local = np.zeros(self.dim) 
    local = [np.random.uniform(-np.pi, np.pi), 0]
    return self.inverse_map(local)

  def pdf(self, p):
    # Uniform.
    if self.sampler['name'] == 'uniform':
      # TODO. Below ignores constraints on p_0, p_1 and might need an almost_equal function.
      if p[2] == implicit_function(p): # Check if on surface. 
        xi = self.map(p) # Points on "inside" of circle around 1-d hole are less likely.
        return (self.R + self.r * (1.0 + np.cos(xi[1]))) / (2.0 * np.pi * (self.R + self.r))
      else:
        return 0.0
    elif self.sampler['name'] == 'bivariate_von_mises':
      raise NotImplementedError
    else:
      raise ValueError(f'Unknown sampler: {self.sampler["name"]}')

  def sample(self, n):
    if self.sampler['name'] == 'uniform':
      raise NotImplementedError
    elif self.sampler['name'] == 'bivariate_von_mises':
      raise NotImplementedError
    else:
      raise ValueError(f'Unknown sampler: {self.sampler["name"]}')

  def grid(self, n):
    assert self.dim == 2
    n_per_dim = int(np.power(n, 1.0 / self.dim))
    local_points = np.zeros([self.dim, n_per_dim])
    local_points[0] = np.linspace(-np.pi, np.pi, n_per_dim)
    local_points[1] = np.linspace(-np.pi, np.pi, n_per_dim)
    local_mesh = np.meshgrid(*local_points)
    local_mesh = np.reshape(local_mesh, [self.dim, -1]).T
    mesh = np.stack([self.inverse_map(local_point) for local_point in local_mesh])
    return mesh 

  def metric_tensor(self, p):
    xi = self.map(p)
    return np.array([
      [(self.R + self.r * np.cos(xi[1])) ** 2, 0.0],
      [0.0, self.r ** 2]
    ])

  def implicit_function(self, p):
    return np.sqrt(self.r ** 2 - (np.sqrt(p[0] ** 2 + p[1] ** 2) - self.R) ** 2)

  def map(self, p):
    xi_0 = np.arctan2(p[1], p[0])
    xi_1 = np.arctan2(p[2], np.sqrt(p[0] ** 2 + p[1] ** 2) - self.R)
    return np.array([xi_0, xi_1])

  def inverse_map(self, xi):
    p_0 = (self.R + self.r * np.cos(xi[1])) * np.cos(xi[0])
    p_1 = (self.R + self.r * np.cos(xi[1])) * np.sin(xi[0])
    p_2 = self.r * np.sin(xi[1])
    return np.array([p_0, p_1, p_2])
