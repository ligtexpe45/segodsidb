"""
@brief   Module that contains the ConfigParser class. It is a lightweight module
         to read the configuration file and the command line parameters and 
         combine them into a single place.

@details The code in this module was inspired by:
         https://github.com/victoresque/pytorch-template

@author  Luis Carlos Garcia Peraza Herrera (luiscarlos.gph@gmail.com).
@date    1 Jun 2021.
"""

import os
import logging
import pathlib
import functools
import operator
import datetime
import json

# My imports
import torchseg.logger
import torchseg.utils


class ConfigParser:
    def __init__(self, config, resume=None, modification=None, run_id=None):
        """
        @class ConfigParser parses the configuration JSON file. Handles 
        hyperparameters for training, initializations of modules, 
        checkpoint saving and logging module.
        @param[in]  config        Dict containing configurations, hyperparameters 
                                  for training. Contents of `config.json` file 
                                  for example.
        @param[in]  resume        String, path to the checkpoint being loaded.
        @param[in]  modification  Dict keychain:value, specifying position values 
                                  to be replaced from config dict.
        @param[in]  run_id        Unique Identifier for training processes. Used 
                                  to save checkpoints and training log. Timestamp 
                                  is being used as default.
        """
        # Load config file and apply modification
        self._config = _update_config(config, modification)
        self.resume = resume

        # Set save_dir where trained model and log will be saved.
        save_dir = pathlib.Path(self.config['machine']['args']['save_dir'])

        exper_name = self.config['name']
        # If no ID is specified, timestamp is used as default run-id
        if run_id is None: 
            run_id = datetime.datetime.now().strftime(r'%d%m_%H%M%S')
        self._save_dir = save_dir / 'models' / exper_name / run_id
        self._log_dir = save_dir / 'log' / exper_name / run_id

        # Make directory for saving checkpoints and log.
        exist_ok = run_id == ''
        self.save_dir.mkdir(parents=True, exist_ok=exist_ok)
        self.log_dir.mkdir(parents=True, exist_ok=exist_ok)

        # Save updated config file to the checkpoint dir
        torchseg.utils.write_json(self.config, self.save_dir / 'config.json')

        # Configure logging module
        torchseg.logger.LoggerSetup(self.log_dir, self.config['logconf'])
        self.log_levels = {
            0: logging.WARNING,
            1: logging.INFO,
            2: logging.DEBUG
        }

    @classmethod
    def from_args(cls, args, options=''):
        """
        @brief Initialize this class from some CLI arguments. Used in training
               and testing.
        """
        for opt in options:
            args.add_argument(*opt.flags, default=None, type=opt.type)
        if not isinstance(args, tuple):
            args = args.parse_args()

        # Select CUDA device (-d option)
        if args.device is not None:
            os.environ["CUDA_VISIBLE_DEVICES"] = args.device
    
        # Setup environment for resuming train/test (-r option)
        if args.resume is not None:
            resume = pathlib.Path(args.resume)
            cfg_fname = resume.parent / 'config.json'
        else:
            msg_no_cfg = "Configuration file need to be specified. \
                Add '-c config.json', for example."
            assert args.conf is not None, msg_no_cfg
            resume = None
            cfg_fname = pathlib.Path(args.conf)
        
        # Setup config (-c option)
        config = torchseg.utils.read_json(cfg_fname)
        if args.conf and resume:
            # Update new config for fine-tuning
            config.update(torchseg.utils.read_json(args.conf))
        
        # Setup log config (-l option)
        if args.logconf:
            config['logconf'] = args.logconf
        else:
            config['logconf'] = ''

        # Parse custom CLI options into dictionary
        modification = {
            opt.target : getattr(args, _get_opt_name(opt.flags)) \
                for opt in options
        }
        return cls(config, resume, modification)

    def init_obj(self, name, module, *args, **kwargs):
        """
        @brief Finds a function handle with the name given as 'type' in config, 
               and returns the instance initialized with corresponding arguments 
               given.
        
        @details `object = config.init_obj('name', module, a, b=1)` is equivalent 
                 to `object = module.name(a, b=1)`
        """
        module_name = self[name]['type']
        module_args = dict(self[name]['args'])
        assert(all([k not in module_args for k in kwargs]))
        #    'Overwriting kwargs given in config file is not allowed'
        module_args.update(kwargs)
        return getattr(module, module_name)(*args, **module_args)

    def init_ftn(self, name, module, *args, **kwargs):
        """
        @brief Finds a function handle with the name given as 'type' in config, 
               and returns the function with given arguments fixed with 
               functools.partial.
        @details `function = config.init_ftn('name', module, a, b=1)`
                 is equivalent to
                 `function = lambda *args, **kwargs: 
                    module.name(a, *args, b=1, **kwargs)`.
        """
        module_name = self[name]['type']
        module_args = dict(self[name]['args'])
        assert(all([k not in module_args for k in kwargs]))
        #    'Overwriting kwargs given in config file is not allowed'
        module_args.update(kwargs)
        return functools.partial(getattr(module, module_name), *args, 
            **module_args)

    def __getitem__(self, name):
        """@brief Access items like ordinary dict."""
        return self.config[name]

    def __str__(self):
        return json.dumps(self.config, sort_keys=True, indent=4)

    def get_logger(self, name, verbosity=2):
        msg_verbosity = 'verbosity option {} is invalid. \
            Valid options are {}.'.format(verbosity, self.log_levels.keys())
        assert verbosity in self.log_levels, msg_verbosity
        logger = logging.getLogger(name)
        logger.setLevel(self.log_levels[verbosity])
        return logger

    # Setting read-only attributes
    @property
    def config(self):
        return self._config

    @property
    def save_dir(self):
        return self._save_dir

    @property
    def log_dir(self):
        return self._log_dir

# Helper functions to update config dict with custom CLI options

def _update_config(config, modification):
    if modification is None:
        return config

    for k, v in modification.items():
        if v is not None:
            _set_by_path(config, k, v)
    return config


def _get_opt_name(flags):
    for flg in flags:
        if flg.startswith('--'):
            return flg.replace('--', '').replace('-', '_')
    return flags[0].replace('--', '').replace('-', '_')


def _set_by_path(tree, keys, value):
    """@brief Set a value in a nested object in tree by sequence of keys."""
    keys = keys.split(';')
    _get_by_path(tree, keys[:-1])[keys[-1]] = value


def _get_by_path(tree, keys):
    """@brief Access a nested object in tree by sequence of keys."""
    return functools.reduce(operator.getitem, keys, tree)
