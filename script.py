import torch
import pytorch_lightning as pl

from torch.utils.data import TensorDataset, DataLoader, random_split
from torch.utils.data import TensorDataset, DataLoader, random_split

from src.models_multimodal import LightCurveImageCLIP
from src.utils import get_valid_dir, LossTrackingCallback, plot_loss_history, get_embs,plot_ROC_curves
from src.dataloader import load_images, load_lightcurves, plot_lightcurve_and_images, NoisyDataLoader


# Data preprocessing

data_dirs = ["/home/thelfer1/scr4_tedwar42/thelfer1/ZTFBTS/",
             "ZTFBTS/",
             "/ocean/projects/phy230064p/shared/ZTFBTS/", 
             "/n/home02/gemzhang/repos/Multimodal-hackathon-2024/ZTFBTS/"]

# Get the first valid directory
data_dir = get_valid_dir(data_dirs)

# Load images from data_dir
host_imgs = load_images(data_dir)

# Load light curves from data_dir
time_ary, mag_ary, magerr_ary, mask_ary, nband = load_lightcurves(data_dir)

# Plot a light curve and its corresponding image
plot_lightcurve_and_images(host_imgs, time_ary, mag_ary, magerr_ary, mask_ary, nband)


time = torch.from_numpy(time_ary).float()
mag = torch.from_numpy(mag_ary).float()
mask = torch.from_numpy(mask_ary).bool()
magerr = torch.from_numpy(magerr_ary).float()

val_fraction = 0.05
batch_size = 32
n_samples_val = int(val_fraction * mag.shape[0])

dataset = TensorDataset(host_imgs, mag, time, mask, magerr)  

dataset_train, dataset_val = random_split(
    dataset, [mag.shape[0] - n_samples_val, n_samples_val]
)
train_loader_no_aug = DataLoader(
    dataset_train, batch_size=batch_size, num_workers=1, pin_memory=True, shuffle=True
)
val_loader_no_aug = DataLoader(
    dataset_val, batch_size=batch_size, num_workers=1, pin_memory=True, shuffle=False
)

# Define the noise levels for images and magnitude (multiplied by magerr)
noise_level_img = 1  # Adjust as needed
noise_level_mag = 1  # Adjust as needed

val_noise = 0

# Create custom noisy data loaders
train_loader = NoisyDataLoader(dataset_train, batch_size=batch_size, noise_level_img=noise_level_img, noise_level_mag=noise_level_mag, shuffle=True, num_workers=1, pin_memory=True)
val_loader = NoisyDataLoader(dataset_val, batch_size=batch_size, noise_level_img=val_noise, noise_level_mag=val_noise, shuffle=False, num_workers=1, pin_memory=True)


transformer_kwargs = {"n_out": 32, "emb": 32, "heads": 2, "depth": 1, "dropout": 0.0}
conv_kwargs = {
    "dim": 32,
    "depth": 2,
    "channels": 3,
    "kernel_size": 5,
    "patch_size": 10,
    "n_out": 32,
    "dropout_prob": 0.0,
}


clip_model = LightCurveImageCLIP(
    logit_scale=20.0,
    lr=1e-4,
    nband=nband,
    loss="softmax",
    transformer_kwargs=transformer_kwargs,
    conv_kwargs=conv_kwargs,
)



# Custom call back for tracking loss
loss_tracking_callback = LossTrackingCallback()

device = "gpu" if torch.cuda.is_available() else "cpu"

trainer = pl.Trainer(max_epochs=10, accelerator=device, callbacks=[loss_tracking_callback]
)
trainer.fit(
    model=clip_model, train_dataloaders=train_loader, val_dataloaders=val_loader
)

plot_loss_history(loss_tracking_callback.train_loss_history, loss_tracking_callback.val_loss_history)

# Get embeddings for all images and light curves
embs_curves_train,embs_images_train = get_embs(clip_model,train_loader_no_aug)
embs_curves_val,embs_images_val = get_embs(clip_model,val_loader_no_aug)

plot_ROC_curves(embs_curves_train,embs_images_train,embs_curves_val,embs_images_val)