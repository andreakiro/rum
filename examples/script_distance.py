from util import visualizer
from manifold import manifold
from density import OnlineKMeansEstimator
from geometry import NeuralDistance
import numpy as np
import argparse
import torch
import time
import logging

logging.basicConfig(level=logging.DEBUG)

# VISUALIZER
SAMLPES_PER_RENDER = 20
MAX_SAMPLES_EXPERIMENT = 1e9
MIN_TIME_RENDER = 0.035
INTERFACE_SCALE = 0.25
RW_STEP_SIZE = 0.2

# PARSER
MANIFOLDS = ['euclidean', 'spherical', 'toroidal', 'hyperpara', 'hyperboloid']
SAMPLERS = ['uniform', 'gaussian', 'vonmises_fisher']
INTERFACES = ['constant', 'xtouch']
SAMPLING = ['rw', 'sample']

# KME
K = 300
LR = 0.5 
BALANCING_STRENGHT = 0.1
HOMEOSTASIS = True
INIT_METHOD = 'uniform'


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    # 1/ manifolds related arguments
    parser.add_argument('--manifold', '-m', type=str, default='toroidal', choices=MANIFOLDS)
    parser.add_argument('--sampler', '-s', type=str, default='uniform', choices=SAMPLERS)
    parser.add_argument('--sampling-type', type=str, default='rw', choices=SAMPLING)
    parser.add_argument('--dim', '-d', type=int, default=2)
    # 2/ visualization related arguments
    parser.add_argument('--interface', '-i', type=str, default='constant', choices=INTERFACES)
    return parser.parse_args()


def get_sampler(args: argparse.Namespace) -> dict:
    assert args.sampler in SAMPLERS, f'Unknown sampler {args.sampler}'

    if args.sampler == 'uniform':
        s = {'type': 'uniform', 'low': -1.0, 'high': 1.0}
    elif args.sampler == 'gaussian':
        s = {'type': 'gaussian', 'mean': 0.0, 'std': 0.1}
    elif args.sampler == 'vonmises_fisher':
        s = {'type': 'vonmises_fisher', 'mu': [0, 1, 0], 'kappa': 10}

    return s


def get_manifold(args: argparse.Namespace) -> manifold.Manifold:
    assert args.manifold in MANIFOLDS, f'Unknown manifold {args.manifold}'

    if args.manifold == 'euclidean':
        sampler = get_sampler(args)
        m = manifold.EuclideanManifold(args.dim, sampler)
    elif args.manifold == 'spherical':
        sampler = get_sampler(args)
        m = manifold.SphericalManifold(args.dim, sampler)
    elif args.manifold == 'toroidal':
        m = manifold.ToroidalManifold(args.dim)
    elif args.manifold == 'hyperpara':
        m = manifold.HyperbolicParaboloidalManifold(args.dim)
    elif args.manifold == 'hyperboloid':
        m = manifold.HyperboloidManifold(args.dim)

    return m


def renderloop() -> None:
    num_samples = 0
    points = None

    while num_samples < MAX_SAMPLES_EXPERIMENT:
        time_start = time.time()
        
        if args.sampling_type == 'sample':
            points = m.sample(SAMLPES_PER_RENDER)
        elif args.sampling_type == 'rw':
            points = m.random_walk(SAMLPES_PER_RENDER, points[-1] if points is not None else None, RW_STEP_SIZE)
        

        state_points = {'name': 'samples', 'points': points, 'color': [0, 255, 0]}
        centroids = {'name': 'centroids', 'points': kmeans.centroids, 'color': [255, 0, 0]}
        
        num_samples += SAMLPES_PER_RENDER
        if K > 3: visualizer.remove('centroids')
        visualizer.add(state_points)
        visualizer.add(centroids)
        visualizer.render()
        
        d.learn(points)
        print(d(x_ref, y_ref))
        kmeans.update(torch.tensor(points))
        
        time_end = time.time()
        time_elapsed = time_end - time_start
        if time_elapsed < MIN_TIME_RENDER:
            time.sleep(MIN_TIME_RENDER - time_elapsed)


if __name__ == '__main__':
    args = get_args()
    print(args)

    m = get_manifold(args)
    d = NeuralDistance(m.ambient_dim, [64, 64], 32)
    visualizer = visualizer.Visualizer(interface=args.interface, defaults={'scale': INTERFACE_SCALE})
    kmeans = OnlineKMeansEstimator(K, m.ambient_dim, LR, BALANCING_STRENGHT, origin=m.starting_state(), init_method=INIT_METHOD, distance_func=d)

    x_ref, y_ref = m.sample(1), m.sample(1)
    visualizer.add({'name': 'references', 'points': np.array([x_ref, y_ref]), 'color': [255, 255, 255]})
    x_ref, y_ref = torch.tensor(x_ref, dtype=torch.float), torch.tensor(y_ref, dtype=torch.float)

    renderloop()
