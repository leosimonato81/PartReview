# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Small 3D vector helpers on Vec3 (pure Python, no numpy)."""

import math

from .models import Vec3


def add(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.x + b.x, a.y + b.y, a.z + b.z)


def sub(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.x - b.x, a.y - b.y, a.z - b.z)


def scale(a: Vec3, k: float) -> Vec3:
    return Vec3(a.x * k, a.y * k, a.z * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def cross(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


def length(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def normalize(a: Vec3) -> Vec3:
    n = length(a)
    if n == 0:
        raise ValueError("cannot normalize a zero vector")
    return scale(a, 1.0 / n)


def distance(a: Vec3, b: Vec3) -> float:
    return length(sub(a, b))


def centroid(points) -> Vec3:
    points = list(points)
    if not points:
        raise ValueError("centroid of no points")
    n = float(len(points))
    return Vec3(sum(p.x for p in points) / n, sum(p.y for p in points) / n,
                sum(p.z for p in points) / n)


def angle_deg(a: Vec3, b: Vec3) -> float:
    c = dot(normalize(a), normalize(b))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def fibonacci_sphere(count: int) -> list[Vec3]:
    """``count`` unit vectors spread evenly over the sphere."""
    if count < 1:
        raise ValueError("count must be >= 1")
    golden = math.pi * (3.0 - math.sqrt(5.0))
    points = []
    for i in range(count):
        z = 1.0 - 2.0 * (i + 0.5) / count
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = golden * i
        points.append(Vec3(r * math.cos(theta), r * math.sin(theta), z))
    return points


def point_segment_distance(p: Vec3, a: Vec3, b: Vec3) -> float:
    """Exact distance from point ``p`` to segment ``ab``."""
    ab = sub(b, a)
    length2 = dot(ab, ab)
    if length2 == 0:
        return distance(p, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / length2))
    return distance(p, add(a, scale(ab, t)))


def point_triangle_distance(p: Vec3, a: Vec3, b: Vec3, c: Vec3) -> float:
    """Exact distance from point ``p`` to triangle ``abc`` (Ericson, RTCD 5.1.5)."""
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return distance(p, a)
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return distance(p, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return distance(p, add(a, scale(ab, v)))
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return distance(p, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return distance(p, add(a, scale(ac, w)))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return distance(p, add(b, scale(sub(c, b), w)))
    denom = 1.0 / (va + vb + vc)
    v, w = vb * denom, vc * denom
    closest = add(a, add(scale(ab, v), scale(ac, w)))
    return distance(p, closest)
