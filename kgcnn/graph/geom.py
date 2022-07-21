import numpy as np


def coulomb_matrix_to_inverse_distance_proton(coulomb_mat: np.ndarray, unit_conversion: float = 1.0):
    r"""Convert a Coulomb matrix back to inverse distancematrix plus atomic number.

    Args:
        coulomb_mat (np.ndarray): Coulomb matrix of shape (...,N,N)
        unit_conversion (float) : Whether to scale units for distance. Default is 1.0.

    Returns:
        tuple: [inv_dist, z]

            - inv_dist (np.ndarray): Inverse distance Matrix of shape (...,N,N).
            - z (np.ndarray): Atom Number corresponding diagonal as proton number (..., N).
    """
    indslie = np.arange(0, coulomb_mat.shape[-1])
    z = coulomb_mat[..., indslie, indslie]
    z = np.power(2 * z, 1 / 2.4)
    a = np.expand_dims(z, axis=len(z.shape) - 1)
    b = np.expand_dims(z, axis=len(z.shape))
    zz = a * b
    c = coulomb_mat / zz
    c[..., indslie, indslie] = 0
    c /= unit_conversion
    z = np.array(np.round(z), dtype=np.int)
    return c, z


def make_rotation_matrix(vector: np.ndarray, angle: float):
    r"""Generate rotation matrix around a given vector with a certain angle.

    Only defined for 3 dimensions explicitly here.

    Args:
        vector (np.ndarray, list): vector of rotation axis (3, ) with (x, y, z).
        angle (value): angle in degrees ° to rotate around.

    Returns:
        np.ndarray: Rotation matrix :math:`R` of shape (3, 3) that performs the rotation for :math:`y = R x`.
    """
    angle = angle / 180.0 * np.pi
    norm = (vector[0] ** 2.0 + vector[1] ** 2.0 + vector[2] ** 2.0) ** 0.5
    direction = vector / norm
    matrix = np.zeros((3, 3))
    matrix[0][0] = direction[0] ** 2.0 * (1.0 - np.cos(angle)) + np.cos(angle)
    matrix[1][1] = direction[1] ** 2.0 * (1.0 - np.cos(angle)) + np.cos(angle)
    matrix[2][2] = direction[2] ** 2.0 * (1.0 - np.cos(angle)) + np.cos(angle)
    matrix[0][1] = direction[0] * direction[1] * (1.0 - np.cos(angle)) - direction[2] * np.sin(angle)
    matrix[1][0] = direction[0] * direction[1] * (1.0 - np.cos(angle)) + direction[2] * np.sin(angle)
    matrix[0][2] = direction[0] * direction[2] * (1.0 - np.cos(angle)) + direction[1] * np.sin(angle)
    matrix[2][0] = direction[0] * direction[2] * (1.0 - np.cos(angle)) - direction[1] * np.sin(angle)
    matrix[1][2] = direction[1] * direction[2] * (1.0 - np.cos(angle)) - direction[0] * np.sin(angle)
    matrix[2][1] = direction[1] * direction[2] * (1.0 - np.cos(angle)) + direction[0] * np.sin(angle)
    return matrix


def rotate_to_principle_axis(coord: np.ndarray):
    r"""Rotate a point-cloud to its principle axis.

    This can be a molecule but also some general data.
    It uses PCA via SVD from :obj:`numpy.linalg.svd`. PCA from scikit uses SVD too (:obj:`scipy.sparse.linalg`).

    .. note::
        The data is centered before SVD but shifted back at the output.

    Args:
        coord (np.array): Array of points forming a pointcloud. Important: coord has shape (N,p)
            where N is the number of samples and p is the feature/coordinate dimension e.g. 3 for x,y,z

    Returns:
        tuple: [R, rotated]

            - R (np.array): Rotation matrix of shape (p, p) if input has (N,p)
            - rotated (np.array): Rotated point-could of coord that was the input.
    """
    centroid_c = np.mean(coord, axis=0)
    sm = coord - centroid_c
    zzt = (np.dot(sm.T, sm))  # Calculate covariance matrix
    u, s, vh = np.linalg.svd(zzt)
    # Alternatively SVD of coord with onyly compute vh but not possible for numpy/scipy.
    rotated = np.dot(sm, vh.T)
    rot_shift = rotated + centroid_c
    return vh, rot_shift


def rigid_transform(a: np.ndarray, b: np.ndarray, correct_reflection: bool = False):
    r"""Rotate and shift point-cloud A to point-cloud B. This should implement Kabsch algorithm.
    May also work for input of shape `(...,N,3)` but is not tested.
    Explanation of Kabsch Algorithm: https://en.wikipedia.org/wiki/Kabsch_algorithm
    For further literature:
    https://link.springer.com/article/10.1007/s10015-016-0265-x
    https://link.springer.com/article/10.1007%2Fs001380050048


    .. note::
        The numbering of points of A and B must match; not for shuffled point-cloud.
        This works for 3 dimensions only. Uses SVD.

    Args:
        a (np.ndarray): list of points (N,3) to rotate (and translate)
        b (np.ndarray): list of points (N,3) to rotate towards: A to B, where the coordinates (3) are (x,y,z)
        correct_reflection (bool): Whether to allow reflections or just rotations. Default is False.

    Returns:
        list: [A_rot, R, t]

            - A_rot (np.ndarray): Rotated and shifted version of A to match B
            - R (np.ndarray): Rotation matrix
            - t (np.ndarray): translation from A to B
    """
    a = np.transpose(np.array(a))
    b = np.transpose(np.array(b))
    centroid_a = np.mean(a, axis=1)
    centroid_b = np.mean(b, axis=1)
    am = a - np.expand_dims(centroid_a, axis=1)
    bm = b - np.expand_dims(centroid_b, axis=1)
    h = np.dot(am, np.transpose(bm))
    u, s, vt = np.linalg.svd(h)
    r = np.dot(vt.T, u.T)
    d = np.linalg.det(r)
    if d < 0:
        print("Warning: det(R)<0, det(R)=", d)
        if correct_reflection:
            print("Correcting R...")
            vt[-1, :] *= -1
            r = np.dot(vt.T, u.T)
    bout = np.dot(r, am) + np.expand_dims(centroid_b, axis=1)
    bout = np.transpose(bout)
    t = np.expand_dims(centroid_b - np.dot(r, centroid_a), axis=0)
    t = t.T
    return bout, r, t


def coordinates_from_distance_matrix(distance: np.ndarray, use_center: bool = None, dim: int = 3):
    r"""Compute list of coordinates from a distance matrix of shape `(N, N)`.
    May also work for input of shape `(..., N, N)` but is not tested.
    Uses vectorized Alogrithm:
    http://scripts.iucr.org/cgi-bin/paper?S0567739478000522
    https://www.researchgate.net/publication/252396528_Stable_calculation_of_coordinates_from_distance_information
    no check of positive semi-definite or possible k-dim >= 3 is done here
    performs svd from numpy

    Args:
        distance (np.ndarray): distance matrix of shape (N,N) with Dij = abs(ri-rj)
        use_center (int): which atom should be the center, dafault = None means center of mass
        dim (int): the dimension of embedding, 3 is default

    Return:
        np.ndarray: List of Atom coordinates [[x_1,x_2,x_3],[x_1,x_2,x_3],...]
    """
    distance = np.array(distance)
    dim_in = distance.shape[-1]
    if use_center is None:
        # Take Center of mass (slightly changed for vectorization assuming d_ii = 0)
        di2 = np.square(distance)
        di02 = 1 / 2 / dim_in / dim_in * (2 * dim_in * np.sum(di2, axis=-1) - np.sum(np.sum(di2, axis=-1), axis=-1))
        mat_m = (np.expand_dims(di02, axis=-2) + np.expand_dims(di02, axis=-1) - di2) / 2  # broadcasting
    else:
        di2 = np.square(distance)
        mat_m = (np.expand_dims(di2[..., use_center], axis=-2) + np.expand_dims(di2[..., use_center],
                                                                                axis=-1) - di2) / 2
    u, s, v = np.linalg.svd(mat_m)
    vecs = np.matmul(u, np.sqrt(np.diag(s)))  # EV are sorted by default
    distout = vecs[..., 0:dim]
    return distout
