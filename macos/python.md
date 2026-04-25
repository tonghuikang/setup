# Python / Conda environments
Please refer to the main document on how to install Anaconda.

[TOC]

In each environment, I will describe how I use it, and quote the installation script.

Selected aliased commands
- `ss` to initialise conda (if not already)
- `sa <env>` to activate the environment
- `clist` to list environment
- (for other commands, please search online)



## Workstation

#### `std`

This is my standard environment with as many packages as I like

```bash
conda create -n code python=3.8
conda activate std
conda install jupyter ipython nb_conda
```

#### `rpa`

This is environment if I need to use the `rpa` package to conduct automated procedures.

```bash
conda create -n code python=3.8
conda activate rpa
conda install jupyter ipython nb_conda
```

Ensure you can run this. At the first time, it should be downloading certain packages.

```python
import rpa as r
r.init()
```


## Competitive programming

Different competitive programming platforms have different sets of allowed libraries. Nevertheless, I install jupyter notebook because I may want run snippets just in time.

#### `code`

This is for competitive programming. We avoid the installation of packages. I would still install 

```bash 
conda create -n code python=3.7
conda install jupyter ipython nb_conda
```

#### `atccoder`

Atcoder allows for more packages

```bash
conda create -n code python=3.8
```


#### `google`

Google Codejam and Hashcode allows for a different set of packages

```bash
conda create -n code python=3.8
```

