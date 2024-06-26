import copy
from typing import Callable, Tuple

import torch
from torch import Tensor

from ..constvars import device, dtype


class KMeansEncoder:

    def __init__(
        self,
        k: int,                     # n_components of (online) kmeans(++)
        dim_states: int,            # dimension of environment states (R^n)
        learning_rate: float,       # alpha - learning rate of kmeans
        balancing_strength: float,  # kappa - balancing strength of kmeans
        man_starting_point: Tensor = None, # starting point of the manifold
        homeostasis: bool = True,   # homeostasis - whether to use homeostasis
        init_method: str = 'uniform', # method to use for initialization of centroids
    ) -> None:
        
        assert k > 0, "Number of clusters k must be greater than 0"
        assert dim_states > 0, "Dimension of environment states must be greater than 0"
        assert 0 < learning_rate <= 1, "Learning rate must be in the range (0, 1]"
        assert balancing_strength >= 0, "Balancing strength must be non-negative"
        assert init_method in ['uniform', 'zeros'], "Initialization method is not supported"

        # kmeans specs
        self.k: int = k
        self.dim_states: int = dim_states

        # tunable hyperparameters
        self.hp_learning_rate: Tensor = torch.tensor(learning_rate, dtype=dtype, device=device)
        self.hp_balancing_strength: Tensor = torch.tensor(balancing_strength, dtype=dtype, device=device)
        self.hp_homeostasis: bool = homeostasis

        # manifold stuff
        self.manifold_starting_point = torch.tensor(man_starting_point).unsqueeze(0) \
            if man_starting_point is not None else torch.zeros((1, self.dim_states), dtype=dtype, device=device)

        # internal kmeans encoder state
        self.centroids: Tensor = self._init_centroids(self.k, self.dim_states, init_method) # mu_i
        self.cluster_sizes: Tensor = torch.zeros((self.k,), dtype=dtype, device=device) # n_i
        self.closest_distances: Tensor = torch.zeros((self.k,), dtype=dtype, device=device) # M_i


    # --- public interface methods ---

    def clone(self) -> 'KMeansEncoder':
        return copy.deepcopy(self)

    def update(self, states: Tensor) -> Tuple['KMeansEncoder', int]:
        # Updates the internal state of the KMeansEncoder with a new state.
        # according to algorithm (1) in https://arxiv.org/pdf/2205.15623.pdf
        assert isinstance(states, Tensor), "States must be torch.Tensor"
        assert states.dim() == 2, "States must be batched (B, dim_states)"
        shuffled_states = states[torch.randperm(states.size(0))]
        closest_cluster_idx = [self._update_single(s) for s in shuffled_states]
        return self, closest_cluster_idx


    def sim_update_v1(self, state: Tensor) -> Tuple['KMeansEncoder']:
        # Simulates a KMeansEncoder update with a new state.
        return self.clone().update(state)


    # --- private interface methods ---

    def _update_single(self, state: Tensor) -> int:
        # Updates the internal state of the KMeansEncoder with a new state.
        # according to algorithm (1) in https://arxiv.org/pdf/2205.15623.pdf

        assert isinstance(state, Tensor), "State must be torch.Tensor"
        assert state.dim() == 1, "State must be a single state (dim_states,)"

        closest_cluster_idx = self._find_closest_cluster(state)
        self._online_update_clusters(state, closest_cluster_idx)
        # CHECK. we dont have anymore access to pathological updates count here.
        # Note: We might want to handle empty clusters here eg. re-init them randomly
        self.closest_distances = self._dist_to_clusters(state, self._euclidean_dist)
        
        return closest_cluster_idx

    def _init_centroids(self, k: int, dim_states: int, method: str = 'kmeans++') -> Tensor:
        if method == 'zeros':
            # Initializes centroids at starting state of the manifold else (0)
            return self.manifold_starting_point.repeat(k, 1)
        elif method == 'uniform':
            # Initializes centroids randomly from a uniform distribution in [-1, 1]^n
            return 2 * torch.rand((k, dim_states), dtype=dtype, device=device) - 1
        else:
            raise ValueError("Invalid initialization method. Choose 'zeros' or 'kmeans++'")
    

    def _euclidean_dist(self, t1: Tensor, t2: Tensor, p: float = 2) -> Tensor:
        # Computes Euclidean distance between two torch.Tensors objects.
        return torch.norm(t1 - t2, p=p, dim=-1)


    def _dist_to_clusters(self, state: Tensor, dist_fn: Callable) -> Tensor:
        # Computes objective distances between a given state and all centroids.
        distances = dist_fn(state.unsqueeze(0), self.centroids.unsqueeze(1)).view(-1)

        if self.hp_homeostasis:
            mean = torch.mean(self.cluster_sizes).item()
            distances += self.hp_balancing_strength * (self.cluster_sizes - mean)
        
        return distances


    def _find_closest_cluster(self, state: Tensor) -> int:
        # Finds the closest cluster and distance to a given state.
        distances: Tensor = self._dist_to_clusters(state, self._euclidean_dist)
        closest_cluster_idx = torch.argmin(distances)
        return closest_cluster_idx.item() # .CHECK for GPU:  might need to .cpu().item()


    def _online_update_clusters(self, state: Tensor, closest_cluster_idx: int) -> None:
        # Online update of closest cluster centroid and size with new state.
        self._update_cluster_centroid(state, closest_cluster_idx)
        self._update_cluster_size(closest_cluster_idx)


    def _update_cluster_centroid(self, state: Tensor, closest_cluster_idx: int) -> None:
        # Online update of closest cluster centroid with new state.
        # Implementation note: learning_rate adjusts based on the cluster size
        # aiding convergence by scaling with the number of points in the cluster
        learning_rate = self.hp_learning_rate / (self.cluster_sizes[closest_cluster_idx] + 1)
        state_contribution = learning_rate * state
        centroid_contribution = (1 - learning_rate) * self.centroids[closest_cluster_idx]
        self.centroids[closest_cluster_idx] = state_contribution + centroid_contribution


    def _update_cluster_size(self, closest_cluster_idx: int) -> None:
        # Online update of closest cluster size with new state.
        self.cluster_sizes[closest_cluster_idx] += 1 # assumes there is one state / update

    