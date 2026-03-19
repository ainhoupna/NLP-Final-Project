import torch
from transformers import AutoTokenizer
from .classifier import BERTClassifier
import os

class MisogynyPredictor:
    def __init__(self, model_path, base_model='bert-base-uncased', device=None):
        self.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(base_model)
        self.model = BERTClassifier(model_name=base_model, num_classes=2)
        
        # Load weights
        state_dict = torch.load(model_path, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state_dict)
        self.model.to(self.device)
        self.model.eval()

    @torch.no_grad()
    def predict_probability(self, text):
        """Returns the probability of the 'misogyny' class (class 1)."""
        inputs = self.tokenizer(
            text, 
            return_tensors="pt", 
            truncation=True, 
            padding=True, 
            max_length=128
        ).to(self.device)
        
        logits = self.model(inputs['input_ids'], inputs['attention_mask'])
        probs = torch.softmax(logits, dim=1)
        # Assuming class 1 is misogyny
        return probs[0][1].item()
