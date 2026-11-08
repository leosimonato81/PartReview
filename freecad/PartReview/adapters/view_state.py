# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""The ONLY place that changes the 3D view (CLAUDE.md rule 3).

``ViewState`` is a context manager. On enter it records visibility and
transparency of every object, the camera and the document's "modified" flag.
Each change made through it (backface culling, node colors) records the
original first. On exit everything is restored, also when an error happened
inside the ``with`` block; the error itself is not swallowed.

Objects are hidden through their scene-graph switch (SoSwitch), not through
the Visibility property: changing the property sets flags that FreeCAD saves
in the file and that the Python API cannot restore exactly (found by
comparing files saved with and without a report; see
tests/freecad/check_saved_file.py). Properties are written back only when
their value really changed, because writing the same value also marks them.
"""

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore
from pivy import coin  # type: ignore


# Objects hidden through the Visibility property instead of the scene switch.
PROPERTY_HIDDEN_PREFIXES = ("Fem::FemPost",)


def _look_rotation(direction, up):
    """SbRotation for a camera looking along ``direction`` with ``up`` on top."""
    z = App.Vector(-direction.x, -direction.y, -direction.z).normalize()
    x = App.Vector(up.x, up.y, up.z).cross(z).normalize()
    y = z.cross(x)
    # Coin uses row vectors: rows are the camera axes in world space.
    return coin.SbRotation(coin.SbMatrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0,
                                         z.x, z.y, z.z, 0, 0, 0, 0, 1))


class ViewState:
    def __init__(self, doc):
        self.doc = doc
        self.gui_doc = Gui.getDocument(doc.Name)
        self.view = self.gui_doc.ActiveView
        self._visibility = {}
        self._transparency = {}
        self._culling = {}
        self._colors = {}
        self._camera = None
        self._modified = None
        self._switches = {}  # object name -> original SoSwitch.whichChild
        self._written = set()  # objects whose Visibility property we had to write
        self._touched_before = set()  # objects already touched (e.g. needing recompute)
        self._overlays = []  # Coin nodes added to the scene for a capture
        self._displaced = set()  # FEM meshes drawn deformed for a capture

    # --- enter / exit ---------------------------------------------------------

    def __enter__(self):
        for obj in self.doc.Objects:
            vo = obj.ViewObject
            if vo is None:
                continue
            self._visibility[obj.Name] = vo.Visibility
            if "Transparency" in vo.PropertiesList:
                self._transparency[obj.Name] = vo.Transparency
        self._camera = self.view.getCamera()
        self._modified = self.gui_doc.Modified
        self._touched_before = {o.Name for o in self.doc.Objects if "Touched" in o.State}
        return self

    def __exit__(self, exc_type, exc, tb):
        self._restore("overlays", self._remove_overlays)
        self._restore("deformed shape", self._undisplace_all)
        self._restore("node colors", self._restore_colors)
        self._restore("backface culling", self._restore_culling)
        self._restore("scene switches", self._restore_switches)
        self._restore("visibility", self._restore_visibility)
        self._restore("touched flags", self._restore_touched)
        self._restore("camera", self._restore_camera)
        self._restore("modified flag", self._restore_modified)
        return False  # never swallow the original error

    def _restore(self, what, action):
        try:
            action()
        except Exception as err:  # rule 5: report with context, keep restoring the rest
            App.Console.PrintError("PartReview ViewState: could not restore %s: %s\n"
                                   % (what, err))

    def _remove_overlays(self):
        root = self.view.getSceneGraph()
        while self._overlays:  # ends: one node removed per pass
            root.removeChild(self._overlays.pop())

    def _restore_colors(self):
        for name, (mode, colors) in self._colors.items():
            vo = self.doc.getObject(name).ViewObject
            vo.resetNodeColor()
            if mode != "Overall":
                vo.NodeColorArray = colors
                vo.ColorMode = mode

    def _restore_culling(self):
        for name, value in self._culling.items():
            vo = self.doc.getObject(name).ViewObject
            if vo.BackfaceCulling != value:
                vo.BackfaceCulling = value

    def _restore_switches(self):
        for name, which in self._switches.items():
            obj = self.doc.getObject(name)
            if obj is not None:
                obj.ViewObject.SwitchNode.whichChild = which

    def _restore_visibility(self):
        """Write back only values that changed (writing marks the property)."""
        for name, value in self._visibility.items():
            obj = self.doc.getObject(name)
            if obj is None:
                continue
            if obj.ViewObject.Visibility != value:
                obj.ViewObject.Visibility = value
            if name in self._transparency and obj.ViewObject.Transparency != self._transparency[name]:
                obj.ViewObject.Transparency = self._transparency[name]

    def _restore_touched(self):
        """Writing Visibility marks the object and its group (e.g. the FEM
        Analysis, via _GroupTouched) as touched, and FreeCAD saves that flag.
        Only for the few objects whose property we wrote, and their groups."""
        if not self._written:
            return
        for name in self._written:
            obj = self.doc.getObject(name)
            if obj is None:
                continue
            candidates = [obj] + [p for p in obj.InList if "_GroupTouched" in p.PropertiesList]
            for target in candidates:
                if target.Name not in self._touched_before:
                    target.purgeTouched()

    def _restore_camera(self):
        self.view.setCamera(self._camera)
        # setCamera() leaves near/far flagged as set even when the saved camera
        # did not have them (Coin defaults); flag them back so the saved
        # camera is byte-identical (checked by tests/freecad/test_view_state.py).
        cam = self.view.getCameraNode()
        for name in ("nearDistance", "farDistance"):
            if name not in self._camera:
                getattr(cam, name).setDefault(True)

    def _restore_modified(self):
        Gui.updateGui()
        self.gui_doc.Modified = self._modified

    # --- changes (each records the original first) ----------------------------

    def show_only(self, objects):
        """Hide everything but ``objects`` in the 3D scene, without touching
        the document (scene-graph switches; see the module docstring)."""
        names = {o.Name for o in objects}
        for obj in self.doc.Objects:
            vo = obj.ViewObject
            if vo is None or obj.Name not in self._visibility:
                continue
            if obj.Name in names:
                if not vo.Visibility:  # hidden by the user: must be shown to be captured
                    self._written.add(obj.Name)
                    vo.Visibility = True  # restored on exit
                continue
            if obj.TypeId.startswith(PROPERTY_HIDDEN_PREFIXES):
                # FEM post-processing objects draw a colour bar outside their
                # scene switch; only hiding the property removes it.
                if vo.Visibility:
                    self._written.add(obj.Name)
                    vo.Visibility = False
                continue
            switch = vo.SwitchNode
            self._switches.setdefault(obj.Name, switch.whichChild.getValue())
            switch.whichChild = -1  # SO_SWITCH_NONE
        Gui.updateGui()

    def set_backface_culling(self, obj, enabled):
        vo = obj.ViewObject
        self._culling.setdefault(obj.Name, vo.BackfaceCulling)
        vo.BackfaceCulling = enabled

    def color_nodes(self, mesh_obj, node_ids, scalars):
        """Color a FEM mesh with scalars in [-1, 1] (see domain/colormap.py)."""
        vo = mesh_obj.ViewObject
        if mesh_obj.Name not in self._colors:
            self._colors[mesh_obj.Name] = (vo.ColorMode, list(vo.NodeColorArray))
        vo.setNodeColorByScalars(list(node_ids), list(scalars))

    def displace(self, mesh_obj, node_ids, vectors, factor):
        """Draw ``mesh_obj`` deformed: node + factor x displacement (view only)."""
        vo = mesh_obj.ViewObject
        vo.setNodeDisplacementByVectors(list(node_ids), list(vectors))
        vo.applyDisplacement(float(factor))
        self._displaced.add(mesh_obj.Name)
        Gui.updateGui()

    def undisplace(self, mesh_obj):
        if mesh_obj.Name in self._displaced:
            mesh_obj.ViewObject.resetNodeDisplacement()
            self._displaced.discard(mesh_obj.Name)
            Gui.updateGui()

    def _undisplace_all(self):
        for name in list(self._displaced):
            obj = self.doc.getObject(name)
            if obj is not None:
                obj.ViewObject.resetNodeDisplacement()
        self._displaced.clear()

    def add_overlay(self, node):
        """Draw an extra Coin node (not a document object) until the context exits."""
        self.view.getSceneGraph().addChild(node)
        self._overlays.append(node)
        Gui.updateGui()

    def remove_overlays(self):
        self._remove_overlays()
        Gui.updateGui()

    def apply_camera(self, spec):
        """Set an orthographic camera from a domain CameraSpec (decision 001)."""
        self.view.setCameraType("Orthographic")
        cam = self.view.getCameraNode()
        cam.orientation.setValue(_look_rotation(spec.direction, spec.up))
        p = spec.position
        cam.position.setValue(coin.SbVec3f(p.x, p.y, p.z))
        cam.focalDistance.setValue(spec.distance)
        cam.nearDistance.setValue(spec.near)
        cam.farDistance.setValue(spec.far)
        cam.height.setValue(spec.height)

    def save_image(self, path, width, height):
        self.view.saveImage(path, width, height, "White")
