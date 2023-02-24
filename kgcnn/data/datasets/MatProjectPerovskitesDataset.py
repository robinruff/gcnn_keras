from kgcnn.data.datasets.MatBenchDataset2020 import MatBenchDataset2020


class MatProjectPerovskitesDataset(MatBenchDataset2020):
    """Store and process :obj:`MatProjectPerovskitesDataset` from `MatBench <https://matbench.materialsproject.org/>`_
    database. Name within Matbench: 'matbench_perovskites'.

    Matbench test dataset for predicting formation energy from crystal structure.
    Adapted from an original dataset generated by Castelli et al. For benchmarking w/ nested cross validation,
    the order of the dataset must be identical to the retrieved data; refer to the Automatminer/Matbench
    publication for more details.

        * Number of samples: 18928
        * Task type: regression
        * Input type: structure

    """

    def __init__(self, reload=False, verbose: int = 10):
        r"""Initialize 'matbench_mp_e_form' dataset.

        Args:
            reload (bool): Whether to reload the data and make new dataset. Default is False.
            verbose (int): Print progress or info for processing where 60=silent. Default is 10.
        """
        # Use default base class init()
        super(MatProjectPerovskitesDataset, self).__init__("matbench_perovskites", reload=reload, verbose=verbose)
        self.label_names = "e_form "
        self.label_units = "eV/unit_cell"
