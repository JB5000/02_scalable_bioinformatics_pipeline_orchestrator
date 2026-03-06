"""
🔗 ALL-TO-ALL INTER-LAYER MODEL
Cada node de uma layer conecta com TODOS os nodes das layers seguintes

Inspirado na tua ideia: "cada node comunica com todos os nodes das layers a seguir"

Arquitetura:
    Layer1 [node1, node2, ..., nodeD] ──┬──→ Layer2
                                         ├──→ Layer3
                                         └──→ Layer4
    
    Cada node da Layer1 contribui para:
    - Todos nodes Layer2
    - Todos nodes Layer3
    - Todos nodes Layer4
    - ...

Complexidade: O(N² × D²) mas APENAS 1 FORWARD PASS!
onde N = número de layers da rede
"""

import torch
import torch.nn as nn


class AllToAllModel(nn.Module):
    """
    All-to-All Inter-Layer Connections
    
        Cada layer recebe input de:
    - Layer anterior (normal)
    - Skip connections de TODAS layers anteriores

        Importante:
        - As saídas dos tokens são geradas APÓS processar todas as layers,
            para que profundidades maiores realmente influenciem os logits.
    """
    
    def __init__(self, vocab_size, seq_len, embed_dim=128, layers=10, dropout=0.1):
        super().__init__()
        
        self.embed = nn.Embedding(vocab_size, embed_dim)
        self.seq_len = seq_len
        self.embed_dim = embed_dim
        self.layers = layers
        
        # Input projection
        self.input_proj = nn.Sequential(
            nn.Linear(seq_len * embed_dim, embed_dim),
            nn.LayerNorm(embed_dim),
            nn.ReLU()
        )
        
        # Processing layers com all-to-all connections
        self.layer_modules = nn.ModuleList()
        
        for i in range(layers):
            # Cada layer recebe:
            # - Seu próprio input (embed_dim)
            # - Contribuições de TODAS layers anteriores (i × embed_dim)
            input_size = embed_dim * (i + 1)
            
            layer = nn.Sequential(
                nn.Linear(input_size, embed_dim),
                nn.LayerNorm(embed_dim),
                nn.ReLU(),
                nn.Dropout(dropout)
            )
            
            self.layer_modules.append(layer)
        
        # Heads de output (1 por token de saída)
        # Sempre seq_len tokens, independentemente do nº de layers.
        output_input_size = embed_dim * layers

        self.output_projs = nn.ModuleList([
            nn.Sequential(
                nn.Linear(output_input_size, embed_dim),
                nn.LayerNorm(embed_dim),
                nn.ReLU(),
                nn.Dropout(dropout)
            )
            for _ in range(seq_len)
        ])

        self.heads = nn.ModuleList([
            nn.Linear(embed_dim, vocab_size)
            for _ in range(seq_len)
        ])
    
    def forward(self, x):
        """
        Forward pass com all-to-all connections
        
        APENAS 1 PASSAGEM mas cada layer vê todas anteriores!
        """
        batch_size = x.size(0)
        
        # Embed e flatten
        embeds = self.embed(x)  # [batch, seq_len, embed_dim]
        flat = embeds.reshape(batch_size, -1)  # [batch, seq_len × embed_dim]
        
        # Initial projection
        h = self.input_proj(flat)  # [batch, embed_dim]
        
        layer_outputs = []
        
        # Process através de todas layers COM all-to-all
        for i in range(self.layers):
            # Build input: h atual + TODAS layers anteriores
            if i == 0:
                layer_input = h
            else:
                # Concatenar com todas layers anteriores
                prev_layers = torch.cat(layer_outputs, dim=1)  # [batch, i × embed_dim]
                layer_input = torch.cat([h, prev_layers], dim=1)  # [batch, (i+1) × embed_dim]
            
            # Process layer i
            h_new = self.layer_modules[i](layer_input)  # [batch, embed_dim]
            layer_outputs.append(h_new)
            
            # Update h para próxima layer (com residual da layer atual)
            h = h_new

        # Contexto global com TODAS as layers
        global_context = torch.cat(layer_outputs, dim=1)  # [batch, layers * embed_dim]

        # Gerar todos os tokens a partir do contexto global
        logits_list = []
        for pos in range(self.seq_len):
            token_h = self.output_projs[pos](global_context)  # [batch, embed_dim]
            logits = self.heads[pos](token_h)                 # [batch, vocab_size]
            logits_list.append(logits)
        
        return logits_list
    
    def count_parameters(self):
        """Count trainable parameters"""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
    
    def estimate_flops_per_forward(self):
        """
        Estimate FLOPs para 1 forward pass
        
        Prova que MESMO com 1 passagem, mais compute = mais tempo
        """
        total_flops = 0
        
        # Embedding lookup (negligible)
        total_flops += self.seq_len * self.embed_dim
        
        # Input projection
        total_flops += 2 * (self.seq_len * self.embed_dim) * self.embed_dim
        
        # Each all-to-all processing layer
        for i in range(self.layers):
            input_size = self.embed_dim * (i + 1)
            # Linear layer: 2 × input × output (multiply-add)
            total_flops += 2 * input_size * self.embed_dim

        # Output projections + heads (sempre seq_len tokens)
        output_input_size = self.embed_dim * self.layers
        for _ in range(self.seq_len):
            total_flops += 2 * output_input_size * self.embed_dim
            total_flops += 2 * self.embed_dim * self.embed.num_embeddings
        
        return total_flops


if __name__ == '__main__':
    print("=" * 70)
    print("All-to-All Inter-Layer Model - Test")
    print("=" * 70)
    
    # Create model
    model = AllToAllModel(
        vocab_size=100,
        seq_len=4,
        embed_dim=128,
        layers=10,
        dropout=0.1
    )
    
    params = model.count_parameters()
    flops = model.estimate_flops_per_forward()
    
    print(f"\nParameters: {params:,}")
    print(f"Estimated FLOPs per forward: {flops:,}")
    
    # Test forward
    x = torch.randint(0, 100, (2, 4))
    outputs = model(x)
    
    print(f"\nInput shape: {x.shape}")
    print(f"Number of outputs: {len(outputs)}")
    print(f"Output shape (each): {outputs[0].shape}")
    
    print("\n✓ Model funciona!")
    print(f"✓ ALL-TO-ALL: cada layer vê TODAS anteriores")
    print(f"✓ APENAS 1 FORWARD PASS para gerar {len(outputs)} tokens")
    print(f"✓ MAS compute é O(N²×D²) = {flops:,} FLOPs")
    print("=" * 70)
