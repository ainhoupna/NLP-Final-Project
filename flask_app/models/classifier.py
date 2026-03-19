import torch
import torch.nn as nn
from transformers import AutoModel

class BERTClassifier(nn.Module):
    """BERT fine-tuning for binary text classification."""

    def __init__(self, model_name='bert-base-uncased', num_classes=2,
                 dropout=0.4, freeze_bert=False):
        super().__init__()
        self.bert = AutoModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(self.bert.config.hidden_size, num_classes)

        if freeze_bert:
            for param in self.bert.parameters():
                param.requires_grad = False

    def forward(self, input_ids, attention_mask):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        # Use [CLS] token representation
        pooled = outputs.last_hidden_state[:, 0]
        pooled = self.dropout(pooled)
        logits = self.classifier(pooled)
        return logits
