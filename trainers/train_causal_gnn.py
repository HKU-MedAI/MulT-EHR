import wandb
import random
from collections import OrderedDict

import dgl
from tqdm import tqdm

import torch
from torch.nn import functional as F

from .trainer import Trainer
from parse import (
    parse_optimizer,
    parse_gnn_model,
)

import plotly.graph_objects as go
from sklearn.manifold import Isomap

from data import load_graph
from utils import metrics
from losses import KLDivergence


class CausalGNNTrainer(Trainer):
    def __init__(self, config: OrderedDict):
        super().__init__(config)

        self.config_gnn = config["GNN"]

        # Initialize GNN model and optimizer
        self.tasks = [
            "readm",
            "mort_pred",
            # "los", "drug_rec"
        ]

        # Load graph, labels and splits
        graph_path = self.config_data["graph_path"]
        labels_path = self.config_data["labels_path"]
        self.graph, self.labels, self.train_mask, self.test_mask = load_graph(graph_path, labels_path)

        # Transform the graph
        self.graph = dgl.AddReverse()(self.graph)

        # Read node_dict
        self.node_dict = {}
        for tp in self.graph.ntypes:
            self.node_dict.update({tp: torch.arange(self.graph.num_nodes(tp))})

        self.gnn = parse_gnn_model(self.config_gnn, self.graph, self.tasks, causal=True).to(self.device)
        self.optimizer = parse_optimizer(self.config_optim, self.gnn)

        self.causal = self.config_train["causal"]

    def train(self) -> None:
        print(f"Start training GNN")

        training_range = tqdm(range(self.n_epoch), nrows=3)

        for epoch in training_range:
            self.gnn.train()
            epoch_stats = {"Epoch": epoch + 1}
            preds, labels = None, None
            losses = []

            # Perform aggregation on visits
            self.optimizer.zero_grad()
            random.shuffle(self.tasks)
            for t in self.tasks:

                indices, labels = self.get_indices_labels(t)

                sg = self.get_subgraphs(indices, "visit")

                preds, rand_feat = self.gnn(sg, "visit", t)

                unif_loss = self.unif_loss(rand_feat) if self.causal else 0

                if t == "drug_rec":
                    preds = preds.sigmoid()
                    loss = F.binary_cross_entropy(preds, labels) + unif_loss * 0.001
                else:
                    loss = F.cross_entropy(preds, labels) + unif_loss * 0.001
                losses.append(loss.view(-1))

            var, mean = torch.var_mean(torch.cat(losses))
            loss = mean + var
            loss.backward()

            self.optimizer.step()

            train_metrics = metrics(preds, labels, "readm")
            # Perform validation and testing
            test_metrics = self.evaluate()

            training_range.set_description_str(
                "Epoch {} | loss: {:.4f}| Train AUC: {:.4f} | Test AUC: {:.4f} | Test ACC: {:.4f} ".format(
                    epoch, loss.item(),
                    train_metrics["tr_accuracy"],
                    test_metrics["readm_roc_auc"],
                    test_metrics["readm_accuracy"]
                )
            )

            epoch_stats.update({"Train Loss: ": loss.item()})
            epoch_stats.update(train_metrics)
            epoch_stats.update(test_metrics)
            self.logging(loss, train_metrics, test_metrics)
            self.visualize_embeddings()
            self.checkpoint_manager.write_new_version(
                self.config,
                self.gnn.state_dict(),
                epoch_stats
            )

            # Remove previous checkpoint
            self.checkpoint_manager.remove_old_version()

    def evaluate(self):
        self.gnn.eval()
        test_metrics = {}
        for t in self.tasks:
            indices, labels = self.get_indices_labels(t, False, -1)

            sg = self.get_subgraphs(indices, "visit")

            with torch.no_grad():
                preds, _ = self.gnn(sg, "visit", t)

            test_metrics.update(metrics(preds, labels, t, prefix=f"{t}"))

        return test_metrics

    def unif_loss(self, feat):
        loss_fcn = KLDivergence()
        unif_feat = torch.rand_like(feat).to(self.device)
        loss = loss_fcn(feat, unif_feat) + loss_fcn(unif_feat, feat)
        return loss

    def get_masks(self, g: dgl.DGLGraph, train: bool, task: str):
        if train:
            masks = self.train_mask[task]
            labels = [self.labels[task][v] for v in masks]
        else:
            masks = self.test_mask[task]
            labels = [self.labels[task][v] for v in masks]

        m = {}

        for tp in g.ntypes:
            if tp == "visit":
                m[tp] = torch.from_numpy(masks.astype("int32"))
            else:
                m[tp] = torch.zeros(0)

        return m

    def get_labels(self, train: bool, task: str):
        if train:
            masks = self.train_mask[task]
            labels = [self.labels[task][v] for v in masks]
        else:
            masks = self.test_mask[task]
            labels = [self.labels[task][v] for v in masks]

        return masks, labels

    def get_subgraphs(self, indices, nt):
        d = self.node_dict.copy()
        d[nt] = self.node_dict[nt][indices]
        sg = self.graph.subgraph(d).to(self.device)

        return sg

    def get_indices_labels(self, t, train=True, cap=3000):
        indices = self.train_mask[t] if train else self.test_mask[t]
        if cap > 0:
            indices = indices[torch.randperm(len(indices))[:cap]]

        if t == "drug_rec":
            all_drugs = self.train_mask["all_drugs"]
            labels = []
            for i in indices:
                drugs = self.labels[t][i]
                labels.append([1 if d in drugs else 0 for d in all_drugs])
            labels = torch.FloatTensor(labels).to(self.device)

        else:
            labels = torch.LongTensor([self.labels[t][i] for i in indices]).to(self.device)

        if t == "mort" and train:
            indices = self.down_sample(indices, labels)
            labels = torch.LongTensor([self.labels[t][i] for i in indices]).to(self.device)

        return indices, labels

    def down_sample(self, indices, labels):
        """
        Down sample labels to ensure data balance
        :param scores:
        :param label:
        :return:
        """
        n = len(labels[labels == 1])
        neg_indices = indices[labels == 0]
        pos_indices = indices[labels == 1]
        neg_indices = neg_indices[torch.randperm(len(neg_indices))[:n]]

        return torch.cat(pos_indices, neg_indices)

    def logging(self, loss, train_metrics, test_metrics):
        wandb.log({"loss": loss})
        wandb.log(train_metrics)
        wandb.log(test_metrics)

    def visualize_embeddings(self):
        embeddings = self.gnn.embeddings.detach().cpu().numpy()[:1000]

        tsne = Isomap(n_components=2)
        embeddings_2d = tsne.fit_transform(embeddings)

        # Create a scatter plot of the embeddings using Plotly
        layout = go.Layout(
            autosize=False,
            width=600,
            height=600)
        fig = go.Figure(data=go.Scatter(x=embeddings_2d[:, 0], y=embeddings_2d[:, 1], mode='markers'), layout=layout)
        wandb.log({"chart": fig})
