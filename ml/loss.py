import torch
import torch.nn as nn
import torch.nn.functional as F

class BatchHardTripletLoss(nn.Module):
    """
    Batch-Hard Triplet Loss.
    For each anchor in a batch, it finds the hardest positive (furthest distance)
    and the hardest negative (closest distance) to form the triplet.
    
    This is highly effective for metric learning as it avoids manual triplet mining.
    """
    def __init__(self, margin: float = 0.5):
        super().__init__()
        self.margin = margin

    def forward(self, embeddings: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        """
        Args:
            embeddings: Tensor of shape (batch_size, embed_dim)
            labels: Tensor of shape (batch_size)
            
        Returns:
            Scalar loss tensor.
        """
        # Compute pairwise distance matrix: dist[i, j] = ||e_i - e_j||_2^2
        # Since embeddings are L2 normalized, ||e_i - e_j||^2 = 2 - 2 * cos_sim(e_i, e_j)
        dist_mat = 2.0 - 2.0 * torch.matmul(embeddings, embeddings.t())
        
        # Prevent negative values due to floating-point precision errors
        dist_mat = torch.clamp(dist_mat, min=0.0)
        
        # Create masks for matching and non-matching labels
        labels_equal = labels.unsqueeze(0) == labels.unsqueeze(1)
        
        # 1. Hardest Positives: Max distance to positive elements
        # Mask out negative entries by setting them to a very small value (0)
        mask_positives = labels_equal.float()
        anchor_positive_dist = dist_mat * mask_positives
        # For each anchor, get the maximum distance to a positive
        hardest_positive_dist, _ = torch.max(anchor_positive_dist, dim=1)
        
        # 2. Hardest Negatives: Min distance to negative elements
        # Mask out positive entries by adding a large offset
        mask_negatives = (~labels_equal).float()
        max_dist, _ = torch.max(dist_mat, dim=1, keepdim=True)
        anchor_negative_dist = dist_mat + max_dist * (1.0 - mask_negatives)
        # For each anchor, get the minimum distance to a negative
        hardest_negative_dist, _ = torch.min(anchor_negative_dist, dim=1)
        
        # 3. Triplet loss calculation
        loss = hardest_positive_dist - hardest_negative_dist + self.margin
        loss = torch.clamp(loss, min=0.0)
        
        return torch.mean(loss)
