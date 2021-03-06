import torch
import time
from tqdm import trange
from sklearn.model_selection import train_test_split
from gwnn_layer import SparseGraphWaveletLayer, DenseGraphWaveletLayer

class GraphWaveletNeuralNetwork(torch.nn.Module):
    """
    Abstract Signed SAGE convolution class.
    :param in_channels: Number of features.
    :param out_channels: Number of filters.
    """
    def __init__(self, args, ncount, feature_number, class_number, device):
        super(GraphWaveletNeuralNetwork, self).__init__()
        self.args = args
        self.ncount = ncount
        self.feature_number = feature_number
        self.class_number = class_number
        self.device = device
        self.setup_layers()

    def setup_layers(self):
        self.convolution_1 = SparseGraphWaveletLayer(self.feature_number, self.args.filters, self.ncount, self.device)
        self.convolution_2 = DenseGraphWaveletLayer(self.args.filters, self.class_number, self.ncount, self.device)

    def forward(self, phi_indices, phi_values, phi_inverse_indices, phi_inverse_values, feature_indices, feature_values):

        deep_features_1 = self.convolution_1(phi_indices, phi_values, phi_inverse_indices, phi_inverse_values, feature_indices, feature_values, self.args.dropout)
        deep_features_2 = self.convolution_2(phi_indices, phi_values, phi_inverse_indices, phi_inverse_values, deep_features_1)
        predictions = torch.nn.functional.log_softmax(deep_features_2, dim=1)
        return predictions
        
class GWNNTrainer(object):


    def __init__(self, args, sparsifier, features, target):
        self.args = args
        self.sparsifier = sparsifier
        self.features = features
        self.target = target
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.setup_logs()
        self.setup_features()
        self.setup_model()
        self.train_test_split()


    def setup_logs(self):
        self.logs = dict()
        self.logs["parameters"] =  vars(self.args)
        self.logs["performance"] = [["Epoch","Loss"]]
        self.logs["training_time"] = [["Epoch","Seconds"]]

    def update_log(self, time, loss, epoch):
        self.epochs.set_description("GWNN (Loss=%g)" % round(loss.item(),4))
        self.logs["performance"].append([epoch, round(loss.item(),4)])
        self.logs["training_time"].append([epoch, time.time()-self.time])

    def setup_features(self):

        self.ncount = self.sparsifier.phi_matrices[0].shape[0]
        self.feature_number = self.features.shape[1]


        self.class_number = max(self.target)+1
        self.target = torch.LongTensor(self.target).to(self.device)

        self.feature_indices = torch.LongTensor(self.features.nonzero()).to(self.device)
        self.feature_values = torch.FloatTensor(self.features[self.features.nonzero()]).view(-1).to(self.device)


        self.phi_indices = torch.LongTensor(self.sparsifier.phi_matrices[0].nonzero()).to(self.device).to(self.device)
        self.phi_values = torch.FloatTensor(self.sparsifier.phi_matrices[0][self.sparsifier.phi_matrices[0].nonzero()]).view(-1).to(self.device)

        self.phi_inverse_indices = torch.LongTensor(self.sparsifier.phi_matrices[1].nonzero()).to(self.device)
        self.phi_inverse_values = torch.FloatTensor(self.sparsifier.phi_matrices[1][self.sparsifier.phi_matrices[1].nonzero()]).view(-1).to(self.device)

    def setup_model(self):
        self.model = GraphWaveletNeuralNetwork(self.args, self.ncount, self.feature_number, self.class_number, self.device).to(self.device)

    def train_test_split(self):
        nodes = [x for x in range(self.ncount)]
        train_nodes, test_nodes = train_test_split(nodes, test_size = self.args.test_size, random_state = self.args.seed)
        self.train_nodes = torch.LongTensor(train_nodes) 
        self.test_nodes = torch.LongTensor(test_nodes)

    def fit(self):
        print("Training.\n")
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.args.learning_rate, weight_decay=self.args.weight_decay)
        self.model.train()
        self.epochs = trange(self.args.epochs, desc="Loss")
        for epoch in self.epochs:
            self.time = time.time()
            self.optimizer.zero_grad()
            prediction = self.model(self.phi_indices, self.phi_values , self.phi_inverse_indices, self.phi_inverse_values, self.feature_indices, self.feature_values)
            loss = torch.nn.functional.nll_loss(prediction[self.train_nodes], self.target[self.train_nodes])
            loss.backward()
            self.optimizer.step()
            self.update_log(time, loss, epoch)

    def score(self):
        print("\nScoring.\n")
        self.model.eval()
        _, prediction = self.model(self.phi_indices, self.phi_values , self.phi_inverse_indices, self.phi_inverse_values, self.feature_indices, self.feature_values).max(dim=1)
        correct = prediction[self.test_nodes].eq(self.target[self.test_nodes]).sum().item()
        accuracy = correct / int(self.ncount*self.args.test_size)
        print("Test Accuracy: {:.4f}".format(accuracy))
        self.logs["accuracy"] = accuracy
