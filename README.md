# [Neural Networks'24] Multi-task Heterogeneous Graph Learning on Electronic Health Records

![image](https://github.com/user-attachments/assets/6dd5a971-8e42-48e5-a807-3a026db75286)


# Dataset

We use the MIMIC-III and MIMIC-IV datasets to benchmark our method.

The download of the data is available at [PhysioNet](https://physionet.org/). You need to complete a short course to obtain access as required by the data issuer. Once you download the data in tabular form, you can construct the graph using `get_graph.py`.

# Training and Testing

The processed data (in `pkl` formats) will be stored in the respective subdirectory under the `data` folder. You may call `main.py` to start a training. Exemplar training configurations are provided in `./config` in yaml formats. Benchmarking is also avaialble in `benchmark.py`. Testing performance will be recorded after every epoch. We adopt `wandb` for results management and results will be uploaded to `wandb` online if switched on. 

# Acknowledgement

We implement our method based on the [pyhealth](https://pyhealth.readthedocs.io/en/latest/) package.

# Citations

If you find our work useful, please cite us at

```
@article{chan2024multi,
  title={Multi-task heterogeneous graph learning on electronic health records},
  author={Chan, Tsai Hor and Yin, Guosheng and Bae, Kyongtae and Yu, Lequan},
  journal={Neural Networks},
  pages={106644},
  year={2024},
  publisher={Elsevier}
}
```
