import numpy as np
import itertools
from .manifold import Manifold, Atlas, Chart
from .util import sphere_sample_uniform

class SphereAtlas(Atlas):
  @staticmethod
  def _chart_0(p):
    return np.array([
      p[0] / (1 + p[2]),
      p[1] / (1 + p[2])
    ])

  @staticmethod
  def _chart_1(p):
    return np.array([
      p[0] / (1 - p[2]),
      p[1] / (1 - p[2])
    ])

  @staticmethod
  def _inverse_chart_0(xi):
    a = xi[0]**2 + xi[1]**2
    return (1 / (a + 1)) * np.array([
      2 * xi[0],
      2 * xi[1],
      1 - a 
    ])

  @staticmethod
  def _inverse_chart_1(xi):
    a = xi[0]**2 + xi[1]**2
    return (1 / (a + 1)) * np.array([
      2 * xi[0],
      2 * xi[1],
      a - 1
    ])

  @staticmethod
  def _norm_0(p, v):
    # TODO. Can optimize by not computing Euclidean norm.
    return (1 + p[2]) * np.linalg.norm(v)

  @staticmethod
  def _norm_1(p, v):
    # TODO. Can optimize by not computing Euclidean norm.
    return (1 - p[2]) * np.linalg.norm(v)

  def __init__(self):
    super(SphereAtlas, self).__init__()
    self.charts = [
      Chart(
        SphereAtlas._chart_0, 
        SphereAtlas._inverse_chart_0, 
        SphereAtlas._norm_0,
      ),
      Chart(
        SphereAtlas._chart_1, 
        SphereAtlas._inverse_chart_1, 
        SphereAtlas._norm_1,
      ),
    ]

  def get_chart(self, p):
    if p[2] >= 0:
      return self.charts[0]
    else:
      return self.charts[1]

class SphereManifold(Manifold):
  # We assume unit radius.
  def __init__(self, dim, sampler):
    assert dim == 2 
    super(SphereManifold, self).__init__(dim, dim + 1)
    self.sampler = sampler
    self.atlas = SphereAtlas()

  def starting_state(self):
    return np.array([0.0, 0.0, 1.0])

  def pdf(self, x):
    if self.sampler['type'] == 'uniform':
      if np.linalg.norm(x) == 1: 
        return 1 / (2 * np.pi)**(self.dim / 2) 
      else:
        return 0.0
    elif self.sampler['type'] == 'vonmises_fisher':
      return scipy.stats.vonmises_fisher.pdf(x, self.sampler['mu'], self.sampler['kappa'])

  def sample(self, n):
    if n > 1: # TODO.
      return np.array([self.sample(1) for _ in range(n)])
    if self.sampler['type'] == 'uniform':
      return sample_uniform(self.dim)
    elif self.sampler['type'] == 'vonmises_fisher':
      return scipy.stats.vonmises_fisher.rvs(self.sampler['mu'], self.sampler['kappa'], size=1)[0]

  def grid(self, n):
    m = int(np.power(n, 1.0 / 3.0))
    points = []
    linspace = np.linspace(-1, 1, m)
    for i, j, k in itertools.product(*([linspace] * 3)):
      points.append(np.array([i,j,k]))
      if np.linalg.norm(points[-1]) > 1:
        points[-1] /= np.linalg.norm(points[-1])
    points = np.array(points)
    return points

  @staticmethod
  def distance_function(x, y):
    return np.arccos(np.dot(x, y))

  def implicit_function(self, p):
    return 1.0 - p[0]**2 - p[1]**2
