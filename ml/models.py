"""
ml/models.py
------------
FingerprintNet  host model. Fuses a 1D ResNet over the per-bit timing-error
                sequence with an MLP over the engineered physical features.
EdgeMLP         tiny features-only model (11 -> 32 -> 16, ~1k parameters) that is
                exported as C arrays and runs on the ESP32 in microseconds.

Both return (embedding, logits). Embeddings are L2-normalised so the triplet
loss and the Mahalanobis authenticator operate in the same space.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from dsp.pulse_dsp import NUM_FEATURES, SEQ_CHANNELS


class ResidualBlock1D(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, stride: int = 1):
        super().__init__()
        self.conv1 = nn.Conv1d(in_ch, out_ch, 3, stride=stride, padding=1, bias=False)
        self.bn1 = nn.BatchNorm1d(out_ch)
        self.conv2 = nn.Conv1d(out_ch, out_ch, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm1d(out_ch)
        self.shortcut = nn.Sequential()
        if stride != 1 or in_ch != out_ch:
            self.shortcut = nn.Sequential(nn.Conv1d(in_ch, out_ch, 1, stride=stride, bias=False),
                                          nn.BatchNorm1d(out_ch))

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        return F.relu(out + self.shortcut(x))


class FingerprintNet(nn.Module):
    def __init__(self, num_classes: int, embedding_dim: int = 32,
                 num_features: int = NUM_FEATURES, seq_channels: int = SEQ_CHANNELS):
        super().__init__()
        self.embedding_dim = embedding_dim
        self.seq = nn.Sequential(
            nn.Conv1d(seq_channels, 16, 5, padding=2, bias=False), nn.BatchNorm1d(16), nn.ReLU(),
            ResidualBlock1D(16, 32), ResidualBlock1D(32, 32, stride=2),
            nn.AdaptiveAvgPool1d(1), nn.Flatten(),
        )
        self.feat = nn.Sequential(nn.Linear(num_features, 48), nn.ReLU(), nn.Linear(48, 32), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(64, 64), nn.ReLU(), nn.Dropout(0.1), nn.Linear(64, embedding_dim))
        self.classifier = nn.Linear(embedding_dim, num_classes)

    def forward(self, feats: torch.Tensor, seq: torch.Tensor):
        z = torch.cat([self.seq(seq), self.feat(feats)], dim=1)
        emb = F.normalize(self.head(z), dim=1)
        return emb, self.classifier(emb * 8.0)


class EdgeMLP(nn.Module):
    """Must stay structurally identical to pa_embed() in phyauth_dsp.c."""

    def __init__(self, num_classes: int, hidden: int = 32, embedding_dim: int = 16,
                 num_features: int = NUM_FEATURES):
        super().__init__()
        self.embedding_dim = embedding_dim
        self.fc1 = nn.Linear(num_features, hidden)
        self.fc2 = nn.Linear(hidden, embedding_dim)
        self.classifier = nn.Linear(embedding_dim, num_classes)

    def forward(self, feats: torch.Tensor, seq: torch.Tensor = None):
        emb = F.normalize(self.fc2(F.relu(self.fc1(feats))), dim=1)
        return emb, self.classifier(emb * 8.0)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
