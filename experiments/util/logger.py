import wandb
from . import analysis

LOCAL_LOG_SCRIPTS = [
  'state'
]

class Logger:
  def __init__(self, cfg, manifold, geometry_estimator, density_estimator):
    # Convert script specification to proper format.
    self.scripts = cfg.scripts if 'scripts' in cfg else {}
    for name, spec in self.scripts.items():
      if type(spec) is int:
        spec = {
          'freq': spec,
          'local': name in LOCAL_LOG_SCRIPTS,
          'params': {} 
        }
      elif type(spec) is dict:
        if 'freq' not in spec:
          raise Exception('Script frequency not specified.')
        if 'local' not in spec:
          spec['local'] = name in LOCAL_LOG_SCRIPTS
        spec['params'] = spec['params'] if 'params' in spec else {}
      else:
        raise Exception('Script specification must be int or dict.')
      self.scripts[name] = spec

    self.manifold = manifold
    self.geometry_estimator = geometry_estimator
    self.density_estimator = density_estimator

  def run_scripts(self, n_iter, samples):
    for name, spec in self.scripts.items():
      if n_iter % spec['freq'] == 0: # Run script.
        script = getattr(analysis, name)
        data = script(
            manifold = self.manifold,
            geometry = self.geometry_estimator, 
            density = self.density_estimator, 
            samples = samples, 
            **spec['params'])
        self.log({name: data})

  def log(self, data, use_wandb=True):
    if use_wandb:
      wandb.log(data)
    else:
      print(data)
