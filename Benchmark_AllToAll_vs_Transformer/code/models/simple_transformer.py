"""
🤖 SIMPLE TRANSFORMER MODEL
Implementação simplificada de Transformer para comparação justa com All-to-All

Componentes:
- Multi-head self-attention
- Feedforward network
- Layer normalization
- Residual connections
"""

import torch
import torch.nn as nn
import math


class MultiHeadAttention(nn.Module):
    """Multi-head self-attention"""
    
    def __init__(self, embed_dim, num_heads=4, dropout=0.1):
        super().__init__()
        assert embed_dim % num_heads == 0
        
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.scale = math.sqrt(self.head_dim)
        
        # Q, K, V projections
        self.qkv = nn.Linear(embed_dim, 3 * embed_dim)
        self.out_proj = nn.Linear(embed_dim, embed_dim)
        self.dropout = nn.Dropout(dropout)
    
    def forward(self, x, mask=None):
        batch, seq_len, embed_dim = x.shape
        
        # Project to Q, K, V
        qkv = self.qkv(x)  # [batch, seq_len, 3*embed_dim]
        qkv = qkv.reshape(batch, seq_len, 3, self.num_heads, self.head_dim)
        qkv = qkv.permute(2, 0, 3, 1, 4)  # [3, batch, heads, seq_len, head_dim]
        q, k, v = qkv[0], qkv[1], qkv[2]
        
        # Attention scores
        scores = (q @ k.transpose(-2, -1)) / self.scale  # [batch, heads, seq_len, seq_len]
        
        if mask is not None:
            scores = scores.masked_fill(mask == 0, float('-inf'))
        
        attn = torch.softmax(scores, dim=-1)
        attn = self.dropout(attn)
        
        # Apply attention to values
        out = attn @ v  # [batch, heads, seq_len, head_dim]
        out = out.transpose(1, 2)  # [batch, seq_len, heads, head_dim]
        out = out.reshape(batch, seq_len, embed_dim)
        
        return self.out_proj(out)


class FeedForward(nn.Module):
    """Position-wise feedforward network"""
    
    def __init__(self, embed_dim, ff_dim=None, dropout=0.1):
        super().__init__()
        if ff_dim is None:
            ff_dim = 4 * embed_dim
        
        self.net = nn.Sequential(
            nn.Linear(embed_dim, ff_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(ff_dim, embed_dim),
            nn.Dropout(dropout)
        )
    
    def forward(self, x):
        return self.net(x)


class TransformerBlock(nn.Module):
    """Single Transformer encoder block"""
    
    def __init__(self, embed_dim, num_heads=4, ff_dim=None, dropout=0.1):
        super().__init__()
        
        self.attention = MultiHeadAttention(embed_dim, num_heads, dropout)
        self.ff = FeedForward(embed_dim, ff_dim, dropout)
        
        self.norm1 = nn.LayerNorm(embed_dim)
        self.norm2 = nn.LayerNorm(embed_dim)
        
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
    
    def forward(self, x, mask=None):
        # Self-attention with residual
        attn_out = self.attention(x, mask)
        x = x + self.dropout1(attn_out)
        x = self.norm1(x)
        
        # Feedforward with residual
        ff_out = self.ff(x)
        x = x + self.dropout2(ff_out)
        x = self.norm2(x)
        
        return x


class SimpleTransformer(nn.Module):
    """
    Simple Transformer for next-token prediction
    
    Similar ao All-to-All: 1 forward pass → todos tokens
    """
    
    def __init__(self, vocab_size, seq_len, embed_dim=128, num_layers=6, 
                 num_heads=4, dropout=0.1):
        super().__init__()
        
        self.embed = nn.Embedding(vocab_size, embed_dim)
        self.pos_embed = nn.Parameter(torch.randn(1, seq_len, embed_dim) * 0.02)
        
        self.blocks = nn.ModuleList([
            TransformerBlock(embed_dim, num_heads, embed_dim * 4, dropout)
            for _ in range(num_layers)
        ])
        
        # Prediction head para cada posição
        self.heads = nn.ModuleList([
            nn.Linear(embed_dim, vocab_size)
            for _ in range(seq_len)
        ])
        
        self.dropout = nn.Dropout(dropout)
        self.seq_len = seq_len
        self.embed_dim = embed_dim
    
    def forward(self, x):
        """
        Forward pass: 1 pass para TODOS tokens
        Como All-to-All!
        """
        batch_size = x.size(0)
        
        # Embeddings
        x = self.embed(x)  # [batch, seq_len, embed_dim]
        x = x + self.pos_embed[:, :x.size(1), :]
        x = self.dropout(x)
        
        # Transformer blocks
        for block in self.blocks:
            x = block(x)  # [batch, seq_len, embed_dim]
        
        # Predict cada posição
        logits_list = []
        for i in range(self.seq_len):
            logits = self.heads[i](x[:, i, :])  # [batch, vocab_size]
            logits_list.append(logits)
        
        return logits_list
    
    def count_parameters(self):
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
    
    def estimate_flops_per_forward(self, batch_size=1):
        """Estimate FLOPs for 1 forward pass"""
        L = self.seq_len
        D = self.embed_dim
        H = 4  # num_heads
        
        total_flops = 0
        
        # Embedding lookup (negligible)
        total_flops += L * D
        
        # Each Transformer block
        for _ in range(len(self.blocks)):
            # Attention: Q,K,V projections
            total_flops += 3 * (2 * L * D * D)
            
            # Attention scores: Q @ K.T
            total_flops += 2 * L * L * D
            
            # Attention output: attn @ V
            total_flops += 2 * L * L * D
            
            # Output projection
            total_flops += 2 * L * D * D
            
            # FFN: 2 linear layers (D → 4D → D)
            total_flops += 2 * L * D * (4 * D)  # First layer
            total_flops += 2 * L * (4 * D) * D  # Second layer
        
        # Prediction heads
        total_flops += L * (2 * D * len(self.heads[0].weight))
        
        return total_flops


if __name__ == '__main__':
    print("=" * 70)
    print("Simple Transformer - Test")
    print("=" * 70)
    
    model = SimpleTransformer(
        vocab_size=100,
        seq_len=4,
        embed_dim=128,
        num_layers=6,
        num_heads=4,
        dropout=0.1
    )
    
    params = model.count_parameters()
    flops = model.estimate_flops_per_forward()
    
    print(f"\nParameters: {params:,}")
    print(f"Estimated FLOPs per forward: {flops:,}")
    
    # Test
    x = torch.randint(0, 100, (2, 4))
    outputs = model(x)
    
    print(f"\nInput shape: {x.shape}")
    print(f"Number of outputs: {len(outputs)}")
    print(f"Output shape (each): {outputs[0].shape}")
    
    print("\n✓ Transformer funciona!")
    print("✓ ENCODER-ONLY: 1 forward pass → todos tokens")
    print(f"✓ Complexity: O(L²×D) attention + O(L×D²) FFN")
    print("=" * 70)
