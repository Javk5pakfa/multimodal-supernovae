import os
from typing import List, Optional
from pytorch_lightning import LightningModule, Trainer
from pytorch_lightning.callbacks import Callback
import torch
import numpy as np
from torch.utils.data import DataLoader
from typing import Tuple, List, Dict
from matplotlib import pyplot as plt
from ruamel.yaml import YAML
from sklearn.linear_model import LinearRegression
from sklearn.svm import LinearSVC
from sklearn.neighbors import KNeighborsRegressor, KNeighborsClassifier
from torch.nn import Module
import pandas as pd


def filter_files(filenames_avail, filenames_to_filter, data_to_filter=None):
    """
    Function to filter filenames and data based on the filenames_avail

    Args:
    filenames_avail (list): List of filenames available
    filenames_to_filter (list): List of filenames to filter
    data_to_filter (List[np.ndarray]): Data to filter based on filenames_to_filter

    Returns:
    inds_filt (np.ndarray): Indices of filtered filenames in filenames_to_filter
    filenames_to_filter (list): List of filtered filenames
    data_to_filter (np.ndarray): Filtered data
    """
    # Check which each filenames_to_filter are available in filenames_avail
    inds_filt = np.isin(filenames_to_filter, filenames_avail)
    if data_to_filter:
        for i in range(len(data_to_filter)):
            data_to_filter[i] = data_to_filter[i][inds_filt]

    filenames_to_filter = np.array(filenames_to_filter)[inds_filt]

    return inds_filt, filenames_to_filter, data_to_filter


def find_indices_in_arrays(st1, st2):
    """
    Find indices of where elements of st1 appear in st2 and indices in st1 of those elements.

    Parameters:
    - st1 (list or array): The list of strings to find in st2.
    - st2 (list or array): The list of strings to search within.

    Returns:
    - tuple of two lists:
        - The first list contains indices indicating where each element of st1 is found in st2.
        - The second list contains the indices in st1 for elements that were found in st2.
    """
    indices_in_st2 = []
    indices_in_st1 = []
    for idx, item in enumerate(st1):
        try:
            index_in_st2 = st2.index(item)  # Find the index of item in st2
            indices_in_st2.append(index_in_st2)
            indices_in_st1.append(idx)
        except ValueError:
            # Item not found in st2, optionally handle it
            continue  # Simply skip if not found
    return indices_in_st2, indices_in_st1


def get_savedir(args) -> str:
    """
    Return config dict and path to save new plots and models based on
    whether to continue from checkpoint or not; dump config file in savedir path

    Args:
    args: argparse.ArgumentParser object

    Returns:
    str: path to save new plots and models
    cfg: dict: configuration dictionary
    """
    # Create directory to save new plots and checkpoints
    import os

    if not os.path.exists("analysis"):
        os.makedirs("analysis")
        os.makedirs("analysis/runs")
    if not os.path.exists("analysis/runs"):
        os.makedirs("analysis/runs")

    # save in checkpoint directory if resuming from checkpoint
    # else save in numbered directory if not given runname
    if args.ckpt_path:
        cfg = YAML(typ="safe").load(
            open(os.path.join(os.path.dirname(args.ckpt_path), "config.yaml"))
        )
        save_dir = os.path.join(os.path.dirname(args.ckpt_path), "resume/")
        os.makedirs(save_dir, exist_ok=True)
    else:
        yaml = YAML(typ="rt")
        cfg = yaml.load(open(args.config_path))
        if args.runname:
            save_dir = f"./analysis/runs/{args.runname}/"
        else:
            dirlist = [
                int(item)
                for item in os.listdir("./analysis/runs/")
                if os.path.isdir(os.path.join("./analysis/runs/", item))
                and item.isnumeric()
            ]
            dirname = str(max(dirlist) + 1) if len(dirlist) > 0 else "0"
            save_dir = os.path.join("./analysis/runs/", dirname)

        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, "config.yaml"), "w") as outfile:
            yaml.dump(cfg, outfile)

    return save_dir, cfg


def set_seed(seed: int = 0) -> None:
    """
    set seed so that results are fully reproducible
    """
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)

    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

    os.environ["PYTHONHASHSEED"] = str(seed)
    print(f"Random seed: {seed}")


def get_valid_dir(data_dirs: List[str]) -> str:
    """
    Returns the first valid directory in the list of directories.

    Args:
    data_dirs (List[str]): A list of directory paths to check.

    Returns:
    str: The first valid directory path found in the list.

    Raises:
    ValueError: If no valid directory is found in the list.
    """
    for data_dir in data_dirs:
        if os.path.isdir(data_dir):
            return data_dir
    raise ValueError("No valid data directory found")


class LossTrackingCallback(Callback):
    def __init__(self):
        self.train_loss_history = []
        self.val_loss_history = []
        self.epoch_train_loss = []
        self.auc_val_history = []
        self.R2_val_history = []
        self.R2_train_history = []

    def on_train_batch_end(self, trainer, pl_module, outputs, batch, batch_idx):
        # Accumulate training loss for each batch
        loss = outputs["loss"] if isinstance(outputs, dict) else outputs
        self.epoch_train_loss.append(loss.detach().item())

    def on_train_epoch_end(self, trainer, pl_module):
        # Append average training loss after each epoch
        epoch_loss = sum(self.epoch_train_loss) / len(self.epoch_train_loss)
        self.train_loss_history.append(epoch_loss)
        self.R2_train_history.append(trainer.callback_metrics.get("R2_train"))
        # Reset the list for the next epoch
        self.epoch_train_loss = []

    def on_validation_epoch_end(self, trainer, pl_module):
        # Append validation loss after each validation epoch
        val_loss = trainer.callback_metrics.get("val_loss")
        if val_loss is not None:
            self.val_loss_history.append(val_loss.detach().item())

    def on_validation_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        auc_val = trainer.callback_metrics.get("AUC_val")
        auc_val1 = trainer.callback_metrics.get("AUC_val1")
        self.R2_val_history.append(trainer.callback_metrics.get("R2_val"))
        if auc_val or auc_val1:
            if auc_val is None:
                auc_val = (
                    sum(
                        [
                            trainer.callback_metrics.get(f"AUC_val{i}").detach().item()
                            for i in range(1, 4)
                        ]
                    )
                    / 3
                )
            else:
                auc_val = auc_val.detach().item()
            self.auc_val_history.append(auc_val)


def plot_loss_history(train_loss_history, val_loss_history, path_base="./"):
    """
    Plots the training and validation loss histories.

    Args:
    train_loss_history (list): A list of training loss values.
    val_loss_history (list): A list of validation loss values.
    """
    # Create a figure and a set of subplots
    plt.figure(figsize=(10, 6))

    # Plot training loss
    plt.plot(
        train_loss_history,
        label="Training Loss",
        color="blue",
        linestyle="-",
        marker="o",
    )

    # Plot validation loss
    plt.plot(
        val_loss_history,
        label="Validation Loss",
        color="red",
        linestyle="-",
        marker="x",
    )

    # Adding title and labels
    plt.title("Training and Validation Loss Over Epochs")
    plt.xlabel("Epochs")
    plt.ylabel("Loss")

    # Adding a legend
    plt.legend()

    # Show grid
    plt.grid(True)

    # Show the plot
    plt.savefig(os.path.join(path_base, "loss_history.png"))


def cosine_similarity(a, b, temperature=1):
    """
    Compute cosine similarity between two tensors.

    Args:
    a (torch.Tensor): First tensor.
    b (torch.Tensor): Second tensor.
    temperature (float): Temperature parameter for scaling the cosine similarity; default is 1.

    Returns:
    torch.Tensor: Cosine similarity between the two tensors.
    """
    a_norm = a / a.norm(dim=-1, keepdim=True)
    b_norm = b / b.norm(dim=-1, keepdim=True)

    logits = a_norm @ b_norm.T * temperature
    return logits.squeeze()


def get_embs(
    clip_model: torch.nn.Module,
    dataloader: DataLoader,
    combinations: List[str],
    ret_combs: bool = False,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Computes and concatenates embeddings for light curves and images from a DataLoader.

    Args:
    clip_model (torch.nn.Module): The model used for generating embeddings.
    dataloader (DataLoader): DataLoader providing batches of data (images, magnitudes, times, masks).
    combinations (List[str]): List of combinations of modalities to use for embeddings.

    Returns:
    List[torch.Tensor]: List of concatenated embeddings for each item in combinations.
    """

    clip_model.eval()
    # getting device of model
    device = next(clip_model.parameters()).device

    embs_list = [[] for i in range(len(combinations))]

    # gives combination names corresponding each emb in embs_list
    combs_all = ["host_galaxy", "lightcurve", "spectral"]
    combs = np.array(combs_all)[np.isin(combs_all, combinations)]

    # Iterate through the DataLoader
    for batch in dataloader:
        x_img, x_lc, t_lc, mask_lc, x_sp, t_sp, mask_sp, _, _ = batch
        if "host_galaxy" in combinations:
            x_img = x_img.to(device)
        if "lightcurve" in combinations:
            x_lc = x_lc.to(device)
            t_lc = t_lc.to(device)
            mask_lc = mask_lc.to(device)
        if "spectral" in combinations:
            x_sp = x_sp.to(device)
            t_sp = t_sp.to(device)
            mask_sp = mask_sp.to(device)

        # Compute embeddings and detach from the computation graph
        with torch.no_grad():
            x = []
            if "host_galaxy" in combinations:
                x.append(clip_model.image_embeddings_with_projection(x_img))
            if "lightcurve" in combinations:
                x.append(
                    clip_model.lightcurve_embeddings_with_projection(
                        x_lc, t_lc, mask_lc
                    )
                )
            if "spectral" in combinations:
                x.append(
                    clip_model.spectral_embeddings_with_projection(x_sp, t_sp, mask_sp)
                )

        # Append the results to the lists
        for i in range(len(x)):
            embs_list[i].append(x[i].detach())

    # Concatenate all embeddings into single tensors
    for i in range(len(embs_list)):
        embs_list[i] = torch.cat(embs_list[i], dim=0)

    if not ret_combs:
        return embs_list
    return embs_list, combs


def get_ROC_data(
    embs1: torch.Tensor, embs2: torch.Tensor
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calculate ROC-like data by evaluating the cosine similarity between two sets of embeddings.

    Args:
    embs1 (torch.Tensor): Tensor of first set of embeddings.
    embs2 (torch.Tensor): Tensor of second set of embeddings.

    Returns:
    Tuple[np.ndarray, np.ndarray]: A tuple containing an array of thresholds and an array of the fraction of correct predictions at each threshold.
    """
    thresholds = np.linspace(0, 1, 100)
    imgs = []

    # Iterate through image embeddings and calculate cosine similarity with curve embeddings
    for idx, emb_src in enumerate(embs2):
        cos_sim = cosine_similarity(embs1, emb_src)
        idx_sorted = torch.argsort(cos_sim, descending=True)

        # Calculate the number of correct predictions for each threshold
        num_right = [
            idx in idx_sorted[: int(threshold * len(idx_sorted))]
            for threshold in thresholds
        ]
        imgs.append(num_right)

    # Calculate the fraction of correct predictions at each threshold
    fraction_correct = np.sum(imgs, axis=0) / len(embs2)

    return thresholds, fraction_correct


def get_AUC(
    embs1: torch.Tensor,
    embs2: torch.Tensor,
) -> Tuple[float, float]:
    """
    Calculate the area under the ROC curve for training and validation datasets.
    Args:
    embs1 (torch.Tensor): Embeddings for first modality.
    embs2 (torch.Tensor): Embeddings for second modality.
    """
    thresholds, fraction_correct = get_ROC_data(embs1, embs2)
    auc = np.trapz(fraction_correct, thresholds)
    return auc


def plot_ROC_curves(
    embs_train: List[torch.Tensor],
    embs_val: List[torch.Tensor],
    combinations: List[str],
    path_base: str = "./",
) -> None:
    """
    Plots ROC-like curves for training and validation datasets based on embeddings.

    Args:
    embs_train (List[torch.Tensor]): List of embeddings for training data.
    embs_val (List[torch.Tensor]): List of embeddings for validation data.
    combinations (List[str]): List of combinations of modalities to use for embeddings.
    path_base (str) : path to save the plot
    """

    combinations = sorted(combinations)

    fractions_train, fractions_val, labels = [], [], []
    for i in range(len(embs_train) - 1):
        for j in range(i + 1, len(embs_train)):
            thresholds, fraction_correct_train = get_ROC_data(
                embs_train[i], embs_train[j]
            )
            thresholds, fraction_correct_val = get_ROC_data(embs_val[i], embs_val[j])
            fractions_train.append(fraction_correct_train)
            fractions_val.append(fraction_correct_val)
            labels.append(f"{combinations[i]} and {combinations[j]}")

    # Set overall figure size and title
    plt.figure(figsize=(12, 6))
    plt.suptitle("Fraction of Correct Predictions vs. Threshold")

    # Plot for validation data
    plt.subplot(1, 2, 1)
    for i, f_val in enumerate(fractions_val):
        plt.plot(thresholds, f_val, lw=2, label=labels[i])
    plt.plot(thresholds, thresholds, linestyle="--", color="gray", label="Random")
    plt.title("Validation Data")
    plt.xlabel("Threshold")
    plt.ylabel("Fraction Correct")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.7)

    # Plot for training data
    plt.subplot(1, 2, 2)
    for i, f_train in enumerate(fractions_train):
        plt.plot(thresholds, f_train, lw=2, label=labels[i])
    plt.plot(thresholds, thresholds, linestyle="--", color="gray", label="Random")
    plt.title("Training Data")
    plt.xlabel("Threshold")
    plt.ylabel("Fraction Correct")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.7)

    # Adjust layout to prevent overlapping
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(os.path.join(path_base, "ROC_curves.png"))


def get_linear_predictions(
    X: torch.Tensor,
    Y: torch.Tensor,
    X_val: Optional[torch.Tensor] = None,
    Y_val: Optional[torch.Tensor] = None,
    task: str = "regression",
) -> torch.Tensor:
    """
    Calculate predictions using a linear regression model (or a linear-kernel SVM, for classification).

    Parameters:
    X (torch.Tensor): The input features for training.
    Y (torch.Tensor): The target values for training.
    X_val (Optional[torch.Tensor]): The input features for validation (default is None).
    Y_val (Optional[torch.Tensor]): The target values for validation (default is None).
    task (str): The downstream task ('regression' or 'classification').

    Returns:
    torch.Tensor: The predictions of the model trained on training data or on validation data if provided.
    """
    # Ensure Y is 2D (necessary for sklearn)
    if len(Y.shape) == 1:
        Y = Y[:, np.newaxis]

    # Convert tensors to numpy
    X = X.cpu().detach().numpy()
    if X_val is not None:
        X_val = X_val.cpu().detach().numpy()

    # fit the model
    if task.lower() == "regression":
        model = LinearRegression().fit(X, Y)
    elif task.lower() == "classification":
        model = LinearSVC().fit(X, Y)
    else:
        raise ValueError("Invalid task")

    # If validation data is provided, make predictions on that, otherwise on training data
    if X_val is not None and Y_val is not None:
        predictions = model.predict(X_val)
    else:
        predictions = model.predict(X)

    # Convert numpy array back to PyTorch tensor
    predictions_tensor = torch.from_numpy(predictions).flatten()

    return predictions_tensor


def get_knn_predictions(
    X: torch.Tensor,
    Y: torch.Tensor,
    X_val: Optional[torch.Tensor] = None,
    Y_val: Optional[torch.Tensor] = None,
    k: int = 5,
    task: str = "regression",
) -> torch.Tensor:
    """
    Calculate predictions using a k-nearest neighbors regression model.

    Parameters:
    X (torch.Tensor): The input features for training.
    Y (torch.Tensor): The target values for training.
    X_val (Optional[torch.Tensor]): The input features for validation (default is None).
    Y_val (Optional[torch.Tensor]): The target values for validation (default is None).
    k (int): The number of neighbors to use for k-nearest neighbors.
    task (str): The downstream task ('regression' or 'classification').

    Returns:
    torch.Tensor: The 1D predictions of the model trained on training data or on validation data if provided.
    """
    # Ensure Y is 2D (necessary for sklearn)
    if len(Y.shape) == 1:
        Y = Y[:, np.newaxis]

    # Convert tensors to numpy
    X = X.cpu().detach().numpy()
    if X_val is not None:
        X_val = X_val.cpu().detach().numpy()

    # fit the model
    if task.lower() == "regression":
        model = KNeighborsRegressor(n_neighbors=k).fit(X, Y)
    elif task.lower() == "classification":
        model = KNeighborsClassifier(n_neighbors=k).fit(X, Y)
    else:
        raise ValueError("Invalid task")

    # If validation data is provided, make predictions on that, otherwise on training data
    if X_val is not None and Y_val is not None:
        predictions = model.predict(X_val)
    else:
        predictions = model.predict(X)

    # Convert numpy array back to PyTorch tensor and flatten to 1D
    predictions_tensor = torch.from_numpy(predictions).flatten()

    return predictions_tensor


def is_subset(subset: List[str], superset: List[str]) -> bool:
    """
    Check if a list of filenames (subset) is completely contained within another list of filenames (superset).

    Args:
    subset (List[str]): A list of filenames to be checked if they are contained within the superset.
    superset (List[str]): A list of filenames that is expected to contain all elements of the subset.

    Returns:
    bool: Returns True if all elements in the subset are found in the superset, otherwise False.
    """
    # Convert lists to sets for efficient subset checking
    subset_set = set(subset)
    superset_set = set(superset)

    # Check if subset is a subset of superset
    return subset_set.issubset(superset_set)


def process_data_loader(
    loader: DataLoader,
    regression: bool,
    classification: bool,
    device: str,
    model: Module,
    combinations: List[str],
) -> Tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]:
    """
    Processes batches from a DataLoader to generate model predictions and true labels for regression or classification.

    Args:
        loader (DataLoader): The DataLoader from which data batches are loaded.
        regression (bool): Indicates whether the processing is for regression tasks.
        classification (bool): Indicates whether the processing is for classification tasks.
        device (str): The device (e.g., 'cuda', 'cpu') to which tensors are sent for model computation.
        model (Module): The neural network model that processes the input data.
        combinations (List[str]): Specifies which types of data (e.g., 'host_galaxy', 'lightcurve', 'spectral') are included in the input batches.

    Returns:
        Tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]: A tuple containing:
            - The true values for the regression or classification targets.
            - The true labels for classification if available.
            - The predicted values from the model if regression is true, otherwise None.
    """
    y_true_val = []
    y_pred_val = []
    y_true_val_label = []

    for batch in loader:
        # Send them all existing tensors to the device
        (
            x_img,
            x_lc,
            t_lc,
            mask_lc,
            x_sp,
            t_sp,
            mask_sp,
            redshift,
            labels,
        ) = batch

        if regression or classification:
            if "host_galaxy" in combinations:  # cfg_extra_args["combinations"]:
                x_img = x_img.to(device)
            if "lightcurve" in combinations:  # cfg_extra_args["combinations"]:
                x_lc = x_lc.to(device)
                t_lc = t_lc.to(device)
                mask_lc = mask_lc.to(device)
            if "spectral" in combinations:  # cfg_extra_args["combinations"]:
                x_sp = x_sp.to(device)
                t_sp = t_sp.to(device)
                mask_sp = mask_sp.to(device)
            x = model(x_img, x_lc, t_lc, mask_lc, x_sp, t_sp, mask_sp)
            y_pred_val.append(x.detach().cpu().flatten())

        y_true_val.append(redshift)
        y_true_val_label.append(labels)

    y_true = torch.cat(y_true_val, dim=0)
    y_true_val_label = torch.cat(y_true_val_label, dim=0)
    if regression:
        y_pred_val = torch.cat(y_pred_val, dim=0)

    return y_true, y_true_val_label, y_pred_val


def print_metrics_in_latex(metrics_list: List[Dict[str, float]]) -> None:
    """
    Generates LaTeX code from a list of metric dictionaries and prints it.

    This function takes a list of dictionaries where each dictionary represents
    performance metrics for a particular model and data combination. It converts
    this list into a DataFrame, formats numerical values to three decimal places,
    and converts the DataFrame to LaTeX format which it then prints.

    Args:
        metrics_list (List[Dict[str, float]]): A list of dictionaries with keys as metric names
                                               and values as their respective numerical values.

    Output:
        None: This function directly prints the LaTeX formatted table to the console.
    """
    metrics_df = pd.DataFrame(metrics_list)

    # Save the DataFrame to a CSV file
    metrics_df.to_csv("model_metrics.csv", index=False)

    # Define formatters for the float columns to format them to three decimal places
    float_formatter = lambda x: f"{x:.4f}"
    formatters = {}

    # Iterate over all metrics and truncate to 3 decimal places
    for colname in list(set(metrics_df.columns.values) - set(["Combination", "Model"])):
        formatters[colname] = float_formatter

    latex_code = metrics_df.to_latex(
        index=False, formatters=formatters, escape=False, na_rep=""
    )

    print(latex_code)
