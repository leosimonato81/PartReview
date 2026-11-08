# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Zienkiewicz-Zhu a-posteriori error estimate for linear elastic tetrahedra.

Reference: O. C. Zienkiewicz and J. Z. Zhu, "A simple error estimator and
adaptive procedure for practical engineering analysis", Int. J. Numer. Meth.
Engng 24 (1987) 337-357; and Zienkiewicz, Taylor & Zhu, "The Finite Element
Method: Its Basis and Fundamentals", chapter on error estimation.

Steps, per element (isotropic linear elasticity, small strains):
1. sigma_h: stress of the FE solution at the Gauss points, from the nodal
   displacements (B matrix of the isoparametric element) and Hooke's law.
2. sigma*: recovered (smoothed) stress: Gauss-point stresses extrapolated to
   the element nodes, averaged over all elements sharing each node, then
   interpolated back with the element shape functions.
3. e^2 = integral of (sigma* - sigma_h) : C : (sigma* - sigma_h) dV, where C
   is the compliance (inverse of Hooke's law); ||u_h||^2 = integral of
   sigma_h : C : sigma_h dV (twice the strain energy).
4. Global relative error in the energy norm:
   eta = sqrt(sum e^2 / (sum ||u_h||^2 + sum e^2)).

Supported: 4-node (1 Gauss point) and 10-node (4 Gauss points) tetrahedra in
SMESH node order. Uses numpy (ships with FreeCAD), hence lives in adapters.
Validated against the analytic cantilever solution: see
tests/freecad/validate_error_estimator.py and decision 005.
"""

from dataclasses import dataclass

import numpy as np  # type: ignore

_A, _B = 0.5854101966249685, 0.1381966011250105  # 4-point rule, degree 2


def _volume_coords(points):
    """(G, 4) volume coordinates L0..L3 from (G, 3) natural coordinates."""
    points = np.asarray(points, dtype=float)
    return np.column_stack([points, 1.0 - points.sum(axis=1)])


_DL_DXI = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [-1.0, -1.0, -1.0]])
_MIDS = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))  # nodes 4..9 (SMESH order)


def _tet10(points):
    """Shape functions (G, 10) and natural derivatives (G, 10, 3) of the 10-node tet."""
    L = _volume_coords(points)
    G = len(L)
    N = np.zeros((G, 10))
    dNdL = np.zeros((G, 10, 4))
    for i in range(4):
        N[:, i] = L[:, i] * (2 * L[:, i] - 1)
        dNdL[:, i, i] = 4 * L[:, i] - 1
    for k, (i, j) in enumerate(_MIDS, start=4):
        N[:, k] = 4 * L[:, i] * L[:, j]
        dNdL[:, k, i] = 4 * L[:, j]
        dNdL[:, k, j] = 4 * L[:, i]
    return N, dNdL @ _DL_DXI


def _tet4(points):
    L = _volume_coords(points)
    return L, np.broadcast_to(_DL_DXI, (len(L), 4, 3)).copy()


RULES = {
    10: (np.array([[_A, _B, _B], [_B, _A, _B], [_B, _B, _A], [_B, _B, _B]]),
         np.full(4, 1.0 / 24.0), _tet10),
    4: (np.array([[0.25, 0.25, 0.25]]), np.array([1.0 / 6.0]), _tet4),
}


@dataclass
class ZZEstimate:
    relative_error: float  # global eta, 0..1
    energy_norm_sq: float  # sum ||u_h||^2 = 2 x strain energy (N.mm with mm/MPa)
    error_norm_sq: float  # sum e^2
    element_relative: np.ndarray  # local eta per element, 0..1
    node_ids: np.ndarray
    node_indicator: np.ndarray  # mean local eta of the elements around each node, 0..1
    node_von_mises: np.ndarray  # von Mises of the recovered stress (MPa), for checking
    invalid_elements: int  # Jacobian determinant of the wrong sign or zero
    element_count: int
    element_error_sq: np.ndarray = None  # ||e||^2 per element (adaptive refinement)


def _compliance_energy(s, lam, mu):
    """s : C : s for isotropic Hooke's law; s has shape (..., 3, 3)."""
    tr = np.trace(s, axis1=-2, axis2=-1)
    ss = np.einsum("...ij,...ij->...", s, s)
    return (ss - lam / (3 * lam + 2 * mu) * tr ** 2) / (2 * mu)


def _von_mises(s):
    dev = s - np.trace(s, axis1=-2, axis2=-1)[..., None, None] * np.eye(3) / 3.0
    return np.sqrt(1.5 * np.einsum("...ij,...ij->...", dev, dev))


def estimate(positions, elements, displacements, youngs_modulus, poisson_ratio):
    """ZZ estimate for one isotropic material.

    positions/displacements: {node id: (x, y, z)} in mm; youngs_modulus in MPa.
    elements: node-id tuples, all 4-node or all 10-node tetrahedra.
    """
    sizes = {len(e) for e in elements}
    if len(sizes) != 1 or next(iter(sizes)) not in RULES:
        raise ValueError("only meshes of a single tetrahedron type (4 or 10 nodes)")
    nodes_per = sizes.pop()
    points, weights, shape = RULES[nodes_per]
    N, dN = shape(points)  # (G, n), (G, n, 3)

    node_ids = np.array(sorted(positions), dtype=np.int64)
    index = {nid: i for i, nid in enumerate(node_ids)}
    conn = np.array([[index[n] for n in e] for e in elements], dtype=np.int64)
    coords = np.array([positions[n] for n in node_ids], dtype=float)
    disp = np.array([displacements[n] for n in node_ids], dtype=float)
    X, U = coords[conn], disp[conn]  # (E, n, 3)

    E, nu = float(youngs_modulus), float(poisson_ratio)
    lam = E * nu / ((1 + nu) * (1 - 2 * nu))
    mu = E / (2 * (1 + nu))

    J = np.einsum("gnd,enk->egdk", dN, X)  # J[d, k] = dx_k / dxi_d
    det = np.linalg.det(J)
    inv = np.linalg.inv(J)
    dNdx = np.einsum("egkd,gnd->egnk", inv, dN)
    H = np.einsum("eni,egnk->egik", U, dNdx)  # displacement gradient du_i/dx_k
    eps = 0.5 * (H + np.swapaxes(H, -1, -2))
    tr = np.trace(eps, axis1=-2, axis2=-1)
    sigma = lam * tr[..., None, None] * np.eye(3) + 2 * mu * eps  # (E, G, 3, 3)

    # Orientation: the mesh's prevailing Jacobian sign; elements with any Gauss
    # point of the other sign (or zero) are inverted/degenerate.
    prevailing = np.sign(np.median(det))
    invalid = int(np.count_nonzero(np.any(det * prevailing <= 0, axis=1)))
    dV = np.abs(det) * weights  # (E, G)

    # Recovery: Gauss-point stresses -> element nodes -> nodal average.
    if nodes_per == 10:
        M = _volume_coords(points)  # M[g, j] = L_j at Gauss point g
        corners = np.einsum("jg,egab->ejab", np.linalg.inv(M), sigma)
        mids = np.stack([(corners[:, i] + corners[:, j]) / 2 for i, j in _MIDS], axis=1)
        element_nodal = np.concatenate([corners, mids], axis=1)
    else:
        element_nodal = np.repeat(sigma, 4, axis=1)
    total = np.zeros((len(node_ids), 3, 3))
    count = np.zeros(len(node_ids))
    np.add.at(total, conn, element_nodal)
    np.add.at(count, conn, 1.0)
    nodal = total / np.maximum(count, 1.0)[:, None, None]
    sigma_star = np.einsum("gn,enab->egab", N, nodal[conn])

    err_sq = np.sum(dV * _compliance_energy(sigma_star - sigma, lam, mu), axis=1)
    norm_sq = np.sum(dV * _compliance_energy(sigma, lam, mu), axis=1)
    total_err, total_norm = float(err_sq.sum()), float(norm_sq.sum())
    eta = np.sqrt(total_err / (total_norm + total_err)) if total_norm + total_err > 0 else 0.0
    local = np.sqrt(err_sq / np.maximum(norm_sq + err_sq, 1e-300))

    indicator_sum = np.zeros(len(node_ids))
    np.add.at(indicator_sum, conn, np.repeat(local[:, None], nodes_per, axis=1))
    indicator = indicator_sum / np.maximum(count, 1.0)

    return ZZEstimate(
        relative_error=float(eta), energy_norm_sq=total_norm, error_norm_sq=total_err,
        element_relative=local, node_ids=node_ids, node_indicator=indicator,
        node_von_mises=_von_mises(nodal), invalid_elements=invalid,
        element_count=len(elements), element_error_sq=err_sq)
