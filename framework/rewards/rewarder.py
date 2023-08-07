from torch import Tensor, FloatTensor

class Rewarder:
    """
    A class representing a reward mechanism for given states.
    This class provides a generic interface for inferring rewards based on states and allows for both inferential
    reward computations as well as learning-based reward computations. Methods include functionalities to infer rewards, 
    compute explicit rewards, and learn from states.
    """
    
    def __init__(self) -> None:
        pass

    def __call__(self, states: Tensor, learn: bool = True) -> FloatTensor:
        """
        Allow the Rewarder object to be callable. This provides a quick way to infer rewards for given states.
        Args:
            states (torch.Tensor): States for which the rewards need to be inferred.
            learn (bool, optional): If True, learn from the states during reward inference. Default is True.
        Returns: FloatTensor: Inferred rewards for the provided states.
        """
        return self.infer(states, learn=learn)

    def infer(self, states: Tensor, learn: bool = True) -> FloatTensor:
        """
        Infer rewards for the given states. This method serves as the main mechanism for reward inference 
        and can be extended or overridden by specific reward models.
        Args:
            states (torch.Tensor): States for which the rewards need to be inferred.
            learn (bool, optional): If True, learn from the states during reward inference. Default is True.
        Returns: FloatTensor: Inferred rewards for the provided states.
        """
        raise NotImplementedError()
    
    def reward(self, states: Tensor) -> FloatTensor:
        """
        Compute explicit rewards for the provided states without any learning. 
        Args: states (torch.Tensor): States for which the rewards are to be computed.
        Returns: FloatTensor: Computed rewards for the provided states.
        """
        return self.infer(states, learn=False)

    def learn(self, states: Tensor) -> None:
        """
        Learn from the provided states. This is an iterative process where the reward mechanism 
        adjusts its internal parameters based on the provided states.
        Args: states (torch.Tensor): States from which the reward mechanism will learn. 
        Returns: None: This method updates the internal state of the rewarder but does not return any value.
        """
        return self.infer(states, learn=True)
    