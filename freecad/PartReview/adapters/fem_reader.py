# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Read a FreeCAD FEM mechanical result into domain models.

Units: FreeCAD stores mechanical result arrays as plain floats in mm / MPa
(see femtaskpanels/task_result_mechanical.py, which labels them the same
way). That storage convention is declared once below. The report shows
values either in fixed engineering units (MPa, mm) or in the user's FreeCAD unit schema,
as chosen in ReportConfig.unit_system (decision 002). Material and
constraint values already carry units in the document.
"""

import FreeCAD as App  # type: ignore

from ..domain.fem_rules import constraint_kind, element_order, is_supported_analysis
from ..domain.models import (
    Constraint,
    ConstraintKind,
    FemResult,
    FieldKind,
    Material,
    material_family,
    MeshInfo,
    ResultField,
    UnitSystem,
    Vec3,
)
from ..domain.units import Quantity, is_raw_unit

# Storage convention of Fem::ResultMechanical arrays (not a display choice).
RESULT_STORAGE_UNITS = {
    FieldKind.VON_MISES: "MPa",
    FieldKind.DISPLACEMENT: "mm",
    FieldKind.PRINCIPAL_MAX: "MPa",
}
RESULT_ARRAYS = {
    FieldKind.VON_MISES: "vonMises",
    FieldKind.DISPLACEMENT: "DisplacementLengths",
    FieldKind.PRINCIPAL_MAX: "PrincipalMax",
}
MESH_LENGTH_UNIT = "mm"  # FreeCAD internal length unit for node coordinates

# Fixed engineering units, used when the report's unit system is MPA_MM
# (decision 002). Matched to a quantity by physical dimension.
# Note: stress and pressure share the dimension, so "MPa" covers both.
MPA_MM_UNITS = ("MPa", "mm", "N", "kg/m^3")

MATERIAL_KEYS = {
    "youngs_modulus": "YoungsModulus",
    "density": "Density",
    "yield_strength": "YieldStrength",
    "ultimate_strength": "UltimateTensileStrength",
}

SOLVER_NAMES = (("Ccx", "CalculiX"), ("Elmer", "Elmer"), ("Z88", "Z88"),
                ("Mystran", "Mystran"))


class FemReadError(Exception):
    """Expected problem with the document; ``key`` is an i18n message key."""

    def __init__(self, key, detail=""):
        super().__init__("%s: %s" % (key, detail) if detail else key)
        self.key = key
        self.detail = detail


# --- discovery ---------------------------------------------------------------

def is_mechanical_result(obj):
    return (obj.TypeId.startswith("Fem::FemResultObject")
            and getattr(obj, "ResultType", "") == "Fem::ResultMechanical")


def list_mechanical_results(doc):
    """[(internal name, label)] of mechanical results in the document."""
    return [(o.Name, o.Label) for o in doc.Objects if is_mechanical_result(o)]


def find_analysis(result_obj):
    for parent in result_obj.InList:
        if parent.TypeId == "Fem::FemAnalysis" or parent.isDerivedFrom("Fem::FemAnalysis"):
            return parent
    return None


# --- units -------------------------------------------------------------------

def to_report_units(quantity, unit_system):
    """FreeCAD Quantity -> domain Quantity in the unit system chosen for the report.

    MPA_MM: fixed engineering units MPa, mm, N, kg/m^3 (decision 002).
    FREECAD_SCHEMA: the user's preferred unit from FreeCAD preferences; when
    the schema has no readable unit for this quantity (FreeCAD returns a raw
    one such as 'kg/(mm*s^2)'), the MPa/mm unit is used for it instead.
    """
    if unit_system is UnitSystem.FREECAD_SCHEMA:
        _text, factor, unit = quantity.getUserPreferred()
        if not is_raw_unit(unit):
            return Quantity(quantity.Value / factor, unit)
    unit = _mpa_mm_unit(quantity)
    if unit is not None:
        return Quantity(quantity.getValueAs(unit).Value, unit)
    App.Console.PrintWarning("PartReview: no MPa/mm unit for %s; using FreeCAD schema\n"
                             % quantity.UserString)
    _text, factor, unit = quantity.getUserPreferred()
    return Quantity(quantity.Value / factor, unit)


def _mpa_mm_unit(quantity):
    """MPa/mm-system unit whose dimension matches ``quantity``; None if no match."""
    for unit in MPA_MM_UNITS:
        if App.Units.Quantity(1.0, unit).Unit == quantity.Unit:
            return unit
    return None


def field_scale(storage_unit, reference_value, unit_system):
    """(scale, unit) to convert raw result values stored in ``storage_unit``.

    In FREECAD_SCHEMA mode the unit is chosen for ``reference_value`` (the
    field maximum), so a whole field uses one consistent unit.
    """
    if unit_system is UnitSystem.MPA_MM:
        return 1.0, storage_unit
    reference = abs(reference_value) or 1.0
    q = App.Units.Quantity(reference, storage_unit)
    _text, factor, unit = q.getUserPreferred()
    if is_raw_unit(unit):  # schema without a readable unit for this quantity
        return 1.0, storage_unit
    return (q.Value / factor) / reference, unit


# --- readers -----------------------------------------------------------------

def read_mesh(mesh_obj):
    fem_mesh = mesh_obj.FemMesh
    for dimension, ids in ((3, fem_mesh.Volumes), (2, fem_mesh.Faces), (1, fem_mesh.Edges)):
        if ids:
            order = element_order(dimension, len(fem_mesh.getElementNodes(ids[0])))
            element_count = len(ids)
            break
    else:
        raise FemReadError("fem.error.empty_mesh", mesh_obj.Label)

    positions = {nid: Vec3(v.x, v.y, v.z) for nid, v in fem_mesh.Nodes.items()}
    return MeshInfo(node_count=len(positions), element_count=element_count,
                    element_order=order, length_unit=MESH_LENGTH_UNIT,
                    node_positions=positions)


def read_fields(result_obj, unit_system):
    node_ids = tuple(result_obj.NodeNumbers)
    fields = {}
    for kind, prop in RESULT_ARRAYS.items():
        raw = getattr(result_obj, prop, None) or []
        if len(raw) != len(node_ids):
            if raw:
                App.Console.PrintWarning(
                    "PartReview: %s.%s has %d values for %d nodes; skipped\n"
                    % (result_obj.Name, prop, len(raw), len(node_ids)))
            continue
        scale, unit = field_scale(RESULT_STORAGE_UNITS[kind], max(raw, key=abs), unit_system)
        fields[kind] = ResultField(kind, unit, node_ids, tuple(v * scale for v in raw))
    if not fields:
        raise FemReadError("fem.error.no_fields", result_obj.Label)
    return fields


def _mpa(text):
    """Material card text (e.g. "3640 MPa", "210 GPa") in MPa, or None."""
    if not text:
        return None
    try:
        return App.Units.Quantity(text).getValueAs("MPa").Value
    except (ValueError, TypeError):
        return None


def _material_quantity(props, key, unit_system):
    text = props.get(key)
    if not text:
        return None
    try:
        return to_report_units(App.Units.Quantity(text), unit_system)
    except (ValueError, TypeError) as err:
        App.Console.PrintWarning("PartReview: material value %s=%r unreadable: %s\n"
                                 % (key, text, err))
        return None


def read_materials(analysis, unit_system):
    materials = []
    for obj in analysis.Group:
        if not obj.isDerivedFrom("App::MaterialObjectPython"):
            continue
        props = obj.Material
        poisson = props.get("PoissonRatio")
        materials.append(Material(
            name=props.get("Name") or obj.Label,
            youngs_modulus=_material_quantity(props, MATERIAL_KEYS["youngs_modulus"], unit_system),
            poisson_ratio=float(poisson) if poisson else None,
            density=_material_quantity(props, MATERIAL_KEYS["density"], unit_system),
            yield_strength=_material_quantity(props, MATERIAL_KEYS["yield_strength"], unit_system),
            ultimate_strength=_material_quantity(props, MATERIAL_KEYS["ultimate_strength"],
                                                 unit_system),
            family=material_family(_mpa(props.get(MATERIAL_KEYS["youngs_modulus"]))),
        ))
    return tuple(materials)


def _references(obj):
    refs = []
    for target, subs in getattr(obj, "References", []) or []:
        for sub in subs or ("",):
            refs.append("%s:%s" % (target.Label, sub) if sub else target.Label)
    return tuple(refs)


def container_placement(target):
    """Placement of the containers (App::Part...) around ``target``.

    ``target.Shape`` already includes the object's own Placement but not the
    one of the App::Part it lives in, while the FEM mesh is in global
    coordinates (verified with examples/teste_app_part.FCStd).
    """
    if not hasattr(target, "getGlobalPlacement") or not hasattr(target, "Placement"):
        return App.Placement()
    return target.getGlobalPlacement().multiply(target.Placement.inverse())


def _reference_lines_points(obj):
    """Discretised CAD edges and vertices of a constraint, global coordinates (mm)."""
    lines, points = [], []
    for target, subs in getattr(obj, "References", []) or []:
        shape = getattr(target, "Shape", None)
        if shape is None:
            continue
        outer = container_placement(target)
        for sub in subs or ():
            if sub.startswith("Edge"):
                edge = shape.getElement(sub).copy()
                pts = [outer.multVec(p) for p in edge.discretize(
                    Deflection=max(0.005, 0.002 * edge.Length))]
                lines += [(Vec3(a.x, a.y, a.z), Vec3(b.x, b.y, b.z)) for a, b in zip(pts, pts[1:])]
            elif sub.startswith("Vertex"):
                p = outer.multVec(shape.getElement(sub).Point)
                points.append(Vec3(p.x, p.y, p.z))
    return tuple(lines), tuple(points)


def _reference_triangles(obj):
    """Tessellated CAD faces of a constraint, in global coordinates (mm).

    Uses the CAD face instead of FemMesh.getNodesByFace, which took ~21 s for
    one large face of a.FCStd. Edges and vertices: see _reference_lines_points.
    """
    triangles = []
    for target, subs in getattr(obj, "References", []) or []:
        shape = getattr(target, "Shape", None)
        if shape is None:
            continue
        outer = container_placement(target)
        for sub in subs or ():
            if not sub.startswith("Face"):
                continue
            # Tessellate a copy: meshing the document's own face clears its
            # BRep "checked" flags, which would then be saved with the file.
            face = shape.getElement(sub).copy()
            tolerance = max(0.01, 0.005 * face.BoundBox.DiagonalLength)
            points, facets = face.tessellate(tolerance)
            points = [outer.multVec(p) for p in points]
            for i, j, k in facets:
                triangles.append(tuple(Vec3(p.x, p.y, p.z) for p in (points[i], points[j], points[k])))
    return tuple(triangles)


def part_faces(analysis):
    """Every face of the parts that supports and loads refer to, tessellated in
    global coordinates: {"Label:FaceN": triangles}. Used to paint supports and
    loads up to the real CAD edges (domain/surface.nearest_faces)."""
    faces, done = {}, set()
    for obj in analysis.Group:
        if constraint_kind(obj.TypeId) is None:
            continue
        for target, _subs in getattr(obj, "References", []) or []:
            shape = getattr(target, "Shape", None)
            if shape is None or target.Name in done:
                continue
            done.add(target.Name)
            outer = container_placement(target)
            for n, face in enumerate(shape.Faces, start=1):
                face = face.copy()  # see _reference_triangles: keep the document clean
                tolerance = max(0.01, 0.005 * face.BoundBox.DiagonalLength)
                points, facets = face.tessellate(tolerance)
                points = [outer.multVec(p) for p in points]
                faces["%s:Face%d" % (target.Label, n)] = tuple(
                    tuple(Vec3(p.x, p.y, p.z) for p in (points[i], points[j], points[k]))
                    for i, j, k in facets)
    return faces


def read_constraints(analysis, unit_system):
    constraints = []
    for obj in analysis.Group:
        kind = constraint_kind(obj.TypeId)
        if kind is None or getattr(obj, "Suppressed", False):
            continue
        magnitude = None
        direction = None
        if kind is ConstraintKind.FORCE:
            magnitude = to_report_units(obj.Force, unit_system)
            d = obj.DirectionVector
            direction = Vec3(d.x, d.y, d.z)
        elif kind is ConstraintKind.PRESSURE:
            magnitude = to_report_units(obj.Pressure, unit_system)
        lines, points = _reference_lines_points(obj)
        constraints.append(Constraint(kind, obj.Label, _references(obj), magnitude, direction,
                                      geometry=_reference_triangles(obj), lines=lines,
                                      points=points))
    return tuple(constraints)


def read_volume_elements(mesh_obj):
    """Node-id tuples of all volume elements (empty for shell/beam meshes)."""
    fem_mesh = mesh_obj.FemMesh
    return tuple(tuple(fem_mesh.getElementNodes(eid)) for eid in fem_mesh.Volumes)


def convert(quantity, unit):
    """Domain Quantity -> same physical value expressed in ``unit``."""
    q = App.Units.Quantity(quantity.value, quantity.unit)
    return Quantity(q.getValueAs(unit).Value, unit)


def parse_quantity_as(text, unit):
    """Parse user text like '250 MPa' and express it in ``unit``.

    Raises FemReadError('config.error.yield') when the text is not a quantity
    of the same kind as ``unit``.
    """
    try:
        q = App.Units.Quantity(text.strip())
        if q.Unit != App.Units.Quantity(1.0, unit).Unit:
            raise ValueError("unit mismatch")
        return Quantity(q.getValueAs(unit).Value, unit)
    except (ValueError, TypeError, ArithmeticError) as err:
        raise FemReadError("config.error.yield", "%r: %s" % (text, err)) from None


def read_displacement_vectors(result_obj):
    """{node id: (ux, uy, uz)} in mm (FreeCAD result storage convention)."""
    return {n: (v.x, v.y, v.z) for n, v in zip(result_obj.NodeNumbers,
                                                result_obj.DisplacementVectors)}


def elastic_constants(analysis):
    """(E in MPa, Poisson ratio) of the single isotropic material, or None.

    None when there is not exactly one material object or a value is missing,
    so that estimates which assume one isotropic material are not made.
    """
    materials = [o for o in analysis.Group if o.isDerivedFrom("App::MaterialObjectPython")]
    if len(materials) != 1:
        return None
    props = materials[0].Material
    young, poisson = props.get("YoungsModulus"), props.get("PoissonRatio")
    if not young or not poisson:
        return None
    try:
        return App.Units.Quantity(young).getValueAs("MPa").Value, float(poisson)
    except (ValueError, TypeError) as err:
        App.Console.PrintWarning("PartReview: elastic constants unreadable: %s\n" % err)
        return None


def solver_meshes(doc, selection=()):
    """FEM meshes that a solver would use (not result meshes), with at least one node.

    Selected meshes win; otherwise every such mesh of the document is returned.
    """
    result_meshes = [getattr(o, "Mesh", None) for o in doc.Objects if is_mechanical_result(o)]

    def usable(obj):
        return (obj.isDerivedFrom("Fem::FemMeshObject")
                and not any(obj is r for r in result_meshes)
                and getattr(obj, "FemMesh", None) is not None and obj.FemMesh.NodeCount > 0)

    selected = [o for o in selection if usable(o)]
    return selected or [o for o in doc.Objects if usable(o)]


def nodal_loads_and_fixed_nodes(analysis):
    """({node: Vec3 load in N}, {fixed node ids}) as FreeCAD writes them for CalculiX.

    Uses FreeCAD's own MeshSetsGetter (the code behind the CalculiX input writer), so
    the nodal loads are the *CLOAD values the solver received. Returns None when it
    cannot be computed (several meshes, no solver, API change...).
    """
    try:
        from femmesh.meshsetsgetter import MeshSetsGetter  # type: ignore
        from femtools.membertools import AnalysisMember  # type: ignore
    except ImportError as err:
        App.Console.PrintWarning("PartReview: FreeCAD FEM tools unavailable: %s\n" % err)
        return None
    result_meshes = [getattr(o, "Mesh", None) for o in analysis.Group if is_mechanical_result(o)]
    meshes = [m for m in analysis.Group if m.isDerivedFrom("Fem::FemMeshObject")
              and not getattr(m, "Suppressed", False)
              and not any(m is r for r in result_meshes)]
    solvers = [o for o in analysis.Group if o.TypeId.startswith("Fem::FemSolverObject")]
    if len(meshes) != 1 or not solvers:
        return None
    try:
        member = AnalysisMember(analysis)
        getter = MeshSetsGetter(analysis, solvers[0], meshes[0], member)
        getter.get_constraints_fixed_nodes()
        getter.get_constraints_force_nodeloads()
        fixed = set()
        for femobj in member.cons_fixed:
            fixed.update(femobj.get("Nodes", ()))
        loads = {}
        for femobj in member.cons_force:
            d = femobj["Object"].DirectionVector
            for _name, table in femobj.get("NodeLoadTable", ()):
                for node, value in table.items():
                    newtons = float(getattr(value, "Value", value))
                    old = loads.get(node, Vec3(0.0, 0.0, 0.0))
                    loads[node] = Vec3(old.x + d.x * newtons, old.y + d.y * newtons,
                                       old.z + d.z * newtons)
        return loads, fixed
    except Exception as err:  # rule 5: FreeCAD internals may change; report, then go on
        App.Console.PrintWarning("PartReview: nodal loads on supports not computed: %s\n"
                                 % err)
        return None


def ccx_dat_text(analysis):
    """Text of the CalculiX .dat output stored in the analysis, or None."""
    for obj in analysis.Group:
        if obj.TypeId == "App::TextDocument" and obj.Name.startswith("ccx_dat_file"):
            return obj.Text
    return None


def read_solver(analysis):
    """(solver name, analysis type) of the first solver in the analysis."""
    for obj in analysis.Group:
        if not obj.TypeId.startswith("Fem::FemSolverObject"):
            continue
        proxy_type = getattr(getattr(obj, "Proxy", None), "Type", "") or obj.TypeId
        name = next((nice for key, nice in SOLVER_NAMES if key in proxy_type), proxy_type)
        return name, str(getattr(obj, "AnalysisType", ""))
    return "", ""


def read_fem_result(doc, result_name, unit_system=UnitSystem.MPA_MM):
    """Build a domain FemResult from the result object called ``result_name``."""
    result_obj = doc.getObject(result_name)
    if result_obj is None:
        raise FemReadError("fem.error.result_not_found", result_name)
    if not is_mechanical_result(result_obj):
        raise FemReadError("fem.error.unsupported_result", result_obj.Label)
    mesh_obj = getattr(result_obj, "Mesh", None)
    if mesh_obj is None:
        raise FemReadError("fem.error.no_mesh", result_obj.Label)
    analysis = find_analysis(result_obj)
    if analysis is None:
        raise FemReadError("fem.error.no_analysis", result_obj.Label)

    solver, analysis_type = read_solver(analysis)
    eigenmode = int(getattr(result_obj, "Eigenmode", 0) or 0)
    if not is_supported_analysis(analysis_type, eigenmode):
        raise FemReadError("fem.error.not_static",
                           "%s (eigenmode %d)" % (analysis_type, eigenmode))
    return FemResult(
        label=result_obj.Label,
        solver=solver,
        analysis_type=analysis_type,
        mesh=read_mesh(mesh_obj),
        fields=read_fields(result_obj, unit_system),
        materials=read_materials(analysis, unit_system),
        constraints=read_constraints(analysis, unit_system),
        elements=read_volume_elements(mesh_obj),
    )
