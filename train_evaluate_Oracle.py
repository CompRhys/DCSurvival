import torchtuples as tt
import torch # For building the networks 
import numpy as np
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
from tqdm import tqdm

from model.oracle_net import WeibullModelClayton, WeibullModel_indep
from torch.utils.data import TensorDataset, DataLoader
import torch.optim as optim

from model.truth_net import Weibull_linear, Weibull_nonlinear
from metrics.metric import surv_diff
from synthetic_dgp import linear_dgp, nonlinear_dgp
from sklearn.model_selection import train_test_split

sample_size=30000
torch.set_num_threads(6)
torch.set_default_tensor_type(torch.DoubleTensor)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
likelihood_threshold = 1e-10


copula_form='Clayton'
method ='uai2023'
risk = 'linear'
print(copula_form)
print(method)
print(risk)

def main(risk="linear"):
    for theta_true in [1,2,3,4,5,6,7,8,9,10,12,14,16,18,20]:
        survival_l1 = []
        for repeat in tqdm(range(5)):
            seed = 142857 + repeat
            rng = np.random.default_rng(seed)
            if risk == 'linear':
                X, observed_time, event_indicator, _, _, beta_e = linear_dgp( copula_name=copula_form, theta=theta_true, sample_size=sample_size, rng=rng, verbose=False)
            elif risk == 'nonlinear':
                X, observed_time, event_indicator, _, _ = nonlinear_dgp( copula_name=copula_form, theta=theta_true, sample_size=sample_size, rng=rng, verbose=False)
            # split train test
            X_train, X_test, y_train, y_test, indicator_train, indicator_test = train_test_split(X, observed_time, event_indicator, test_size=0.33, 
                                                                                                 stratify= event_indicator, random_state=repeat)
            # split train val
            # X_train, X_val, y_train, y_val, indicator_train, indicator_val = train_test_split(X_train, y_train, indicator_train, test_size=0.33)

            if method=='uai2023':
                times_tensor_train = torch.tensor(y_train).to(device)
                event_indicator_tensor_train = torch.tensor(indicator_train).to(device)
                covariate_tensor_train = torch.tensor(X_train).to(device)
                dataset = TensorDataset(covariate_tensor_train, times_tensor_train, event_indicator_tensor_train)     
                batch_size = 1024  # set your batch size
                dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

                model = WeibullModelClayton(X.shape[1]).to(device)
                optimizer_event = optim.Adam([{"params": [model.scale_t], "lr": 0.01},
                                            {"params": [model.shape_t], "lr": 0.01},
                                            {"params": model.net_t.parameters(), "lr": 0.01},
                                        ])
                optimizer_censoring = optim.Adam([{"params": [model.scale_c], "lr": 0.01},
                                            {"params": [model.shape_c], "lr": 0.01},
                                            {"params": model.net_c.parameters(), "lr": 0.01},
                                        ])
                optimizer_theta = optim.Adam([{"params": [model.theta], "lr": 0.01}])  
                num_epochs = 10000
                # Train the model
                for epoch in range(num_epochs):
                    for covariates, times, events in dataloader:  # iterate over batches
                        optimizer_theta.zero_grad()
                        optimizer_event.zero_grad()
                        optimizer_censoring.zero_grad()
                        log_likelihood, event_log_density, event_partial_copula, censoring_log_density, censoring_partial_copula = \
                            model.log_likelihood(covariates, times, events)
                        (-log_likelihood).backward()
                        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1)
                        optimizer_censoring.step()
                        optimizer_event.step()
                        if epoch > 1000: 
                            optimizer_theta.step()                       
                        if -log_likelihood.item() < likelihood_threshold:
                            break

            if risk == "linear":
                truth_model = Weibull_linear(num_feature= X_test.shape[1], shape = 4, scale = 14, device = torch.device("cpu"), coeff = beta_e)
            elif risk == "nonlinear":
                truth_model = Weibull_nonlinear(shape = 4, scale = 17, device = torch.device("cpu"))

            # calculate survival_l1 based on ground truth survival function
            steps = np.linspace(y_test.min(), y_test.max(), 10000)
            performance = surv_diff(truth_model, model, X_test, steps)
            survival_l1.append(performance)
        print("theta_true = ", theta_true, "survival_l1 = ", np.nanmean(survival_l1), "+-", np.nanstd(survival_l1))

if __name__ == "__main__":
    main(risk="nonlinear")