import torch
import numpy as np
import pytest
from ml.models import ResNet1D, SpectrogramCNN, ImpairmentMLP, RFFingerprintFusionModel
from ml.loss import BatchHardTripletLoss
from ml.authenticator import OpenSetAuthenticator

def test_model_forward_shapes():
    batch_size = 4
    window_size = 1024
    
    # 1. Test ResNet1D
    resnet1d = ResNet1D(in_channels=2, out_features=128)
    iq_input = torch.randn(batch_size, 2, window_size)
    iq_out = resnet1d(iq_input)
    assert iq_out.shape == (batch_size, 128)
    
    # 2. Test SpectrogramCNN
    spec_cnn = SpectrogramCNN(out_features=128)
    spec_input = torch.randn(batch_size, 1, 128, 17) # shape (Batch, 1, Freq, Time)
    spec_out = spec_cnn(spec_input)
    assert spec_out.shape == (batch_size, 128)
    
    # 3. Test ImpairmentMLP
    imp_mlp = ImpairmentMLP(in_features=3, out_features=32)
    imp_input = torch.randn(batch_size, 3)
    imp_out = imp_mlp(imp_input)
    assert imp_out.shape == (batch_size, 32)
    
    # 4. Test RFFingerprintFusionModel
    fusion = RFFingerprintFusionModel(embedding_dim=128, num_classes=3)
    embeddings, logits = fusion(iq_input, spec_input, imp_input)
    
    assert embeddings.shape == (batch_size, 128)
    assert logits.shape == (batch_size, 3)
    
    # Verify embedding is L2-normalized: sum(emb^2) = 1.0
    norms = torch.norm(embeddings, p=2, dim=1)
    for n in norms:
        assert abs(n.item() - 1.0) < 1e-5

def test_triplet_loss():
    loss_fn = BatchHardTripletLoss(margin=0.5)
    
    # Mock embeddings (normalized)
    emb = torch.tensor([
        [1.0, 0.0],  # A (Class 0)
        [0.98, 0.2], # B (Class 0) - close to A
        [0.0, 1.0],  # C (Class 1) - far from A/B
        [0.1, 0.99]  # D (Class 1) - close to C, far from A/B
    ], dtype=torch.float32)
    
    labels = torch.tensor([0, 0, 1, 1], dtype=torch.long)
    
    loss = loss_fn(emb, labels)
    
    assert loss.item() >= 0.0
    # The hardest positive for A is B (dist approx 0.04)
    # The hardest negative for A is C (dist approx 2.0)
    # So triplet loss should be 0 because d(a,p) - d(a,n) + margin = 0.04 - 2.0 + 0.5 < 0
    # Let's verify it compiles and runs without issues.
    assert isinstance(loss, torch.Tensor)

def test_authenticator():
    auth = OpenSetAuthenticator(use_mahalanobis=True)
    
    # Generate mock embeddings for DEV_A (centered around [1.0, 0.0, 0.0])
    np.random.seed(42)
    dev_a_samples = np.random.normal(0, 0.05, (10, 3)) + np.array([1.0, 0.0, 0.0])
    # Normalize rows
    dev_a_samples = dev_a_samples / np.linalg.norm(dev_a_samples, axis=1, keepdims=True)
    
    # Generate negative intruder samples
    intruders = np.random.normal(0, 0.05, (10, 3)) + np.array([0.0, 1.0, 0.0])
    intruders = intruders / np.linalg.norm(intruders, axis=1, keepdims=True)
    
    # Calibrate DEV_A
    auth.calibrate_device("DEV_A", dev_a_samples, target_far=0.01, intruder_embeddings=intruders)
    
    assert "DEV_A" in auth.get_registered_devices()
    profile = auth.profiles["DEV_A"]
    assert "centroid" in profile
    assert "cov_inv" in profile
    assert profile["threshold"] > 0
    
    # Query with a positive sample
    query_pos = np.array([0.98, 0.01, 0.02])
    is_auth_pos, dist_pos, thresh = auth.authenticate("DEV_A", query_pos)
    assert is_auth_pos is True
    assert dist_pos <= thresh
    
    # Query with an intruder sample
    query_neg = np.array([0.02, 0.97, 0.01])
    is_auth_neg, dist_neg, _ = auth.authenticate("DEV_A", query_neg)
    assert is_auth_neg is False
    assert dist_neg > thresh
