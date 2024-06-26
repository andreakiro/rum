from rum.density.density import Density
from rum.density.entropic_functions import EntropicFunction
from rum.learner.learner import Learner
from rum.geometry import Geometry, EuclideanGeometry
from rum.manifold import Manifold # Needed for initialization under natural geometry.
from torch import Tensor, LongTensor, FloatTensor
from typing import Union, Optional, Tuple
import numpy as np
import torch
import os

class OnlineKMeansEstimator(Density, Learner):

    DEFAULT_LR = 0.1
    DEFAULT_BS = 0.1
    DEFAULT_INIT = 'uniform'
    DEFAULT_DEVICE = torch.device('cpu')
    DEFAULT_DTYPE = torch.float32

    def __init__(
        self,
        k: int,
        dim: int,
        # learning hyperparameters
        homeostasis: bool = True,
        force_sparse: bool = True,
        init_method: str = DEFAULT_INIT,
        learning_rate: float = DEFAULT_LR,
        balancing_strength: float = DEFAULT_BS,
        origin: Union[Tensor, np.ndarray] = None,
        entropic_func: EntropicFunction = None,
        # manifold geometry functions
        geometry: Geometry = EuclideanGeometry,
        # torch device and dtype
        device: torch.device = torch.device('cpu'),
        dtype: torch.dtype = torch.float32,
        # learner buffer
        buffer_size: int = 1000,
    ):
        Density.__init__(self, dim)
        Learner.__init__(self, dim, buffer_size)

        if not isinstance(k, int) or k <= 0:
            raise ValueError("Number of clusters k must be greater than 0")
        if not isinstance(learning_rate, float) or not 0 < learning_rate <= 1:
            raise ValueError("Learning rate must be in the range (0, 1]")
        if not isinstance(balancing_strength, float) or balancing_strength < 0:
            raise ValueError("Balancing strength must be non-negative")
        if init_method not in ['uniform', 'zeros', 'gaussian']:
            raise ValueError("Initialization method is not supported")
        if origin is not None and (not isinstance(origin, Tensor) or origin.shape != (dim,)):
            raise ValueError("Origin centroid must be Tensor of shape (dim,)")

        self.k: int = k
        self.dim: int = dim
        self.device: torch.device = device
        self.dtype: torch.dtype = dtype

        if device == torch.device('cuda'):
            self.num_cuda_cores_per_device = 1024  # varies by GPU
            self.num_threads = torch.cuda.device_count() * self.num_cuda_cores_per_device
        else:
            # Use the number of CPU cores if on CPU
            self.num_threads = os.cpu_count()

        # Initialization
        self.init_method: str = init_method
        self.origin = origin if origin is not None else \
            torch.zeros((1, self.dim), dtype=self.dtype, device=self.device)

        # Hyperparameters
        self.lr: float = learning_rate
        self.bs: float = balancing_strength
        self.homeostasis: bool = homeostasis
        self.force_sparse: bool = force_sparse
        self.entropic_func = entropic_func if entropic_func is not None \
            else EntropicFunction("log", eps=1e-9)

        # Underlying manifold geometry functions
        self.geometry = geometry

        # Internal k-Means state
        self.centroids: Tensor = self._init_centroids() # (k, dim)
        self.cluster_sizes: Tensor = torch.zeros((self.k,), device=self.device) # (k,)

        m = self._pairwise_distance() # (k,k)
        # Diameters of each cluster and closest cluster idx
        self.diameters = torch.min(m, dim=1).values # (k,)
        self.closest_idx = torch.argmin(m, dim=1) # (k,)

        # Logging for experiments
        self.n_pathological = 0


    # --- Public interface methods ---

    def learn(self, states: Tensor, num_passes: int = 1, shuffling: bool = True) -> None:
        """
        WARNING: Updates internal state of current object.
        Updates the k-means state given a batch of states
        Params: states: (B, dim) batch of states
        Time-complexity: O(B * k * Pathological * dim)
        """
        if not isinstance(states, Tensor) or states.dim() != 2:
            raise ValueError("States must be tensor of shape (B, dim)")
        
        B, k = states.shape[0], self.k # batch size, number clusters
        states = states.requires_grad_(False) # detach any gradients

        # distances, _ = self._find_closest_cluster(states) # (B,)
        # objective = self.kmeans_objective(distances)

        if shuffling:
            shuffle = torch.randperm(B)
            states = states[shuffle] # (B, dim)
        
        n_pathological = 0

        for pass_idx in range(num_passes):
            if B <= k or self.force_sparse:
                # Centroids sequential. Diameters sparse.
                for s in states:
                    # Cannot be parallelized.
                    closest_idx = self._update_single(s)
                    _, _, n_patho = self._diameters_sparse(closest_idx, inplace=True)
                    n_pathological += n_patho
            else:
                # Centroids sequential. Diameters pairwise.
                for s in states: _ = self._update_single(s)
                self._diameters_pairwise()

        # Logging for experiments
        self.n_pathological = n_pathological


    def simulate_step(self, state: Tensor) -> Tensor:
        """
        Simulates a step of the k-means algorithm on given state
        Params: state: (dim,) state to simulate step on
        Returns: (K,) diameters of each clusters
        Time-complexity: O(K * Pathological * dim)
        """
        if not isinstance(state, Tensor) or state.dim() != 1:
            raise ValueError("State must be of shape (dim,)")
        _, closest_idx = self._find_closest_cluster(state.unsqueeze(0)) # (1,)
        # Simulate centroids update
        centroids = self.centroids.clone()
        centroids[closest_idx] = self._compute_centroid_pos(state, closest_idx)
        # Simulate sparse diameters update
        diameters, _, _ = self._diameters_sparse(closest_idx, inplace=False, centroids=centroids)
        return diameters
    

    # --- k-Means density estimators methods ---

    def kmeans_objective(self, distances: Tensor) -> Tensor:
        """
        Computes the k-means objective given distance to centroids
        Params: distances: (B,)
        Returns: (1,) k-means objective
        Time-complexity: O(B)
        """
        if not isinstance(distances, Tensor) and distances.dim() != 1:
            raise ValueError("States must be Tensor of shape (B,)")
        km_objective = torch.sum(distances.pow(2)) # (1,)
        return km_objective # (1,)

    def pdf(self, x: Tensor) -> float:
        return self.pdf_approx(x, self.diameters)

    def pdf_approx(self, x: Tensor, diameters: Optional[Tensor] = None) -> Tensor:
        """
        Computes the upper bound of the pdf of the k-means state
        Params: x: (dim,) point at which to compute pdf
        Returns: (1,) upper bound of the pdf
        Time-complexity: O(k)
        """
        _, closest_idx = self._find_closest_cluster(x.unsqueeze(0))
        ds = self.diameters if diameters is None else diameters
        return 1 / (ds[closest_idx[0]] + 1e-6)
    
    def information(self, x: Tensor, diameters: Optional[Tensor] = None) -> Tensor:
        """
        Computes the information of a state in the k-means
        Params: x: (dim,) point at which to compute information
        Params: diameters: (k,) diameters of each clusters
        Returns: (1,) lower bound of the information
        Time-complexity: O(k)
        """
        pdf_approx = self.pdf_approx(x, diameters)
        return self.entropic_func(pdf_approx)

    def entropy(self) -> Tensor:
        return self.entropy_lb(self.diameters)

    def entropy_lb(self, diameters: Optional[Tensor] = None) -> Tensor:
        """
        Computes the lower bound of the entropy of the k-means state
        Params: diameters: (k,) diameters of each clusters
        Returns: (1,) lower bound of the entropy
        Time-complexity: O(k)
        """
        if not isinstance(diameters, Tensor) and diameters.dim() != 1:
            raise ValueError("Diameters must be Tensor of shape (k,)")
        # ds = self.diameters if diameters is None else diameters
        entropies = self.entropic_func(diameters) # (k,)
        return torch.sum(entropies) # (1,)

    # --- kMeans state update private methods ---

    def _init_centroids(self) -> Tensor:
        """
        Initializes the centroids of the k-means state
        Returns: (k, dim) centroids
        Time-complexity: O(k * dim)
        """
        if self.init_method == 'zeros':
            return self.origin.repeat(self.k, 1)
        elif self.init_method == 'uniform':
          if isinstance(self.geometry, Manifold): # This is very hacky.
            assert self.geometry.sampler['name'] == 'uniform'
            return torch.Tensor(self.geometry.sample(self.k))
          else:
            return 2 * torch.rand((self.k, self.dim), dtype=self.dtype, device=self.device) - 1
        elif self.init_method == 'gaussian':
            assert not isinstance(self.geometry, Manifold)
            cov = torch.eye(self.dim, dtype=self.dtype, device=self.device)
            return torch.distributions.MultivariateNormal(self.origin, cov).sample((self.k,)).clamp(-1, 1)


    def _update_single(self, state: Tensor) -> None:
        """
        WARNING: Updates internal state of current object.
        Updates the k-means state given a single state
        Params: state: (dim,) state to update on
        Time-complexity: O(Distance) + O(Interpolate) + O(k)
        """
        if not isinstance(state, Tensor) or state.dim() != 1:
            raise ValueError("State must be of shape (dim,)")
        _, closest_idx = self._find_closest_cluster(state.unsqueeze(0)) # ci(1,)
        self.centroids[closest_idx] = self._compute_centroid_pos(state, closest_idx)
        self.cluster_sizes[closest_idx] += 1
        return closest_idx # (1,)


    def _find_closest_cluster(self, states: Tensor) -> Tuple[Tensor, Tensor]:
        """
        Find closest cluster assignment and distance for each states in batch
        Params: states: (B, dim)
        Returns: distances: (B,) closest_idx: (B,)
        Time-complexity: O(Distance) + O(B * k)
        """
        if not isinstance(states, Tensor) or states.dim() != 2:
            raise ValueError("States must be of shape (B, dim)")
        
        batch_size = states.shape[0]
        distances, closest_idx = torch.zeros((batch_size)), torch.zeros((batch_size), dtype=torch.long)

        for i, s in enumerate(states):
            ds = self._weighted_distance(s) # (k,)
            d, ci = torch.min(ds, dim=0) # (1,)
            distances[i] = d
            closest_idx[i] = ci

        return distances, closest_idx # (B,)


    def _weighted_distance(self, state: Tensor) -> FloatTensor:
        """
        Computes the weighted distance of a state to the centroids
        Params: state: (1, dim) state to compute distance to
        Returns: (1,) weighted distance
        Time-complexity: O(Distance) + O(k)
        """
        if not isinstance(state, Tensor) or state.dim() != 1:
            raise ValueError("State must be of shape (dim,)")

        s, cs = state.unsqueeze(0), self.centroids  # s(1, dim) cs(k, dim) 
        distances: Tensor = self.geometry.distance_function(s, cs).view(-1) # distances(k,)

        if self.homeostasis:
            mean = torch.mean(self.cluster_sizes)
            adj = self.bs * (self.cluster_sizes - mean)
            distances += adj # TODO. Clip to 0?

        return distances


    def _compute_centroid_pos(self, state: Tensor, closest_idx: Tensor) -> Tensor:
        """
        Computes the centroid position after a single update
        Params: state: (dim,) closest_idx: (1,)
        Returns: (dim,) centroid
        Time-complexity: O(Interpolate)
        """
        if not isinstance(state, Tensor) or state.dim() != 1:
            raise ValueError("State must be of shape (dim,)")
        if not isinstance(closest_idx, Tensor) or closest_idx.shape != (1,):
            raise ValueError("Closest_idx must be of shape (1,)")
        c = self.centroids[closest_idx].reshape(-1) # (dim,)
        return self.geometry.interpolate(c, state, self.lr) # (dim,)


    # --- kMeans diameters private methods ---

    def _diameters_sparse(
            self, updated_idx: LongTensor, inplace: bool, centroids: Tensor = None
    ) -> Tuple[Tensor, Tensor, int]:
        """
        WARNING: Can update internal state of current object.
        Updates the diameters of k-means in sparse fashion
        Params: updated_idx: (1,) index of updated centroid
                inplace: (bool) whether to update internal state
                centroids: (k, dim) centroids to use for update
        Returns: diameters: (k,) closest_idx: (k,) n_pathological: (int)
        Time-complexity: (k * Pathological * dim)
        """

        # 0) Setup variables to be updated
        centroids = self.centroids if centroids is None else centroids
        diameters = self.diameters if inplace else self.diameters.clone()
        closest_idx = self.closest_idx if inplace else self.closest_idx.clone()

        # 1) Compute distances from the updated centroid to all others
        centroid = centroids[updated_idx]  # (1, dim)
        new_diameters = self.geometry.distance_function(centroid, centroids)  # (k,)
        new_diameters[updated_idx] = float('inf')  # exclude updated centroid itself

        # 2) Update closest distances and idx of updated centroid
        min_val, min_idx = torch.min(new_diameters, dim=0)
        diameters[updated_idx] = min_val.item()
        closest_idx[updated_idx] = min_idx.item()

        # 3) Check if the update affected any other centroids
        closer_mask = new_diameters < diameters
        diameters[closer_mask] = new_diameters[closer_mask]
        closest_idx[closer_mask] = updated_idx

        # 4) Identify pathological cases and count them
        referencing_mask = closest_idx == updated_idx
        pathological_mask = referencing_mask & ~closer_mask
        pathological_idx = torch.nonzero(pathological_mask).squeeze(0)
        n_pathological = pathological_mask.sum().item()

        # 5) Recompute distances for pathological cases

        if n_pathological > 0:
            if n_pathological == 1:
                pathological_idx = pathological_idx.unsqueeze(0)

            patho_diameters = torch.zeros(n_pathological, dtype=self.dtype, device=self.device)
            patho_closest_idx = torch.zeros(n_pathological, dtype=torch.long, device=self.device)

            for i, idx in enumerate(pathological_idx):
                # Avoiding parallelization here due to the overhead from spawning threads
                # n_pathological is about 1-2% of k, making parallelism less beneficial
                c = self.centroids[idx]  # (1, dim)
                d = self.geometry.distance_function(c, centroids)  # (k,)
                d[idx] = float('inf')  # exclude centroid itself
                min_val, min_idx = torch.min(d, dim=0)
                patho_diameters[i] = min_val
                patho_closest_idx[i] = min_idx
            
            diameters[pathological_mask] = patho_diameters
            closest_idx[pathological_mask] = patho_closest_idx

        return diameters, closest_idx, n_pathological
    

    def _diameters_pairwise(self, diag: float = float('inf')) -> None:
        """
        WARNING: Updates internal state of current object.
        Updates the diameters of k-means in pairwise fashion
        Params: diag: (float) value to fill diagonal with
        Time-complexity: O(k^2 * dim)
        """
        m = self._pairwise_distance(diag) # (k, k)
        min_val, min_idx = torch.min(m, dim=1)
        self.diameters = min_val # (k,)
        self.closest_idx = min_idx # (k,)


    def _pairwise_distance(self, diag: float = float('inf')) -> Tensor:
        """
        Computes the pairwise distance between centroids
        Params: diag: (float) value to fill diagonal with
        Returns: (k, k) pairwise distance matrix
        Time-complexity: O(k^2 * dim)
        """
        m = torch.zeros(self.k, self.k, device=self.device)
        x = self.centroids.unsqueeze(0)
        y = self.centroids.unsqueeze(1)
        m = torch.norm(x - y, dim=2, p=2)
        m.fill_diagonal_(diag)
        return m
