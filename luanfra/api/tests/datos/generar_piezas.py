"""
Genera piezas STEP de verdad con geometría B-rep, no ficheros de texto simulados.
Así las pruebas del reconocedor se hacen sobre sólidos reales.
"""
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer
from OCP.BRepPrimAPI import (BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder)
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

AQUI = Path(__file__).parent


def guardar(forma, nombre):
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    w = STEPControl_Writer()
    w.Transfer(forma, STEPControl_AsIs)
    w.Write(str(AQUI / nombre))
    print("  ->", nombre)


def eje_escalonado():
    """ø50×200 con escalón a ø40 y agujero pasante ø10 en el eje."""
    tramo1 = BRepPrimAPI_MakeCylinder(25.0, 120.0).Shape()
    ax = gp_Ax2(gp_Pnt(0, 0, 120), gp_Dir(0, 0, 1))
    tramo2 = BRepPrimAPI_MakeCylinder(ax, 20.0, 80.0).Shape()
    eje = BRepAlgoAPI_Fuse(tramo1, tramo2).Shape()
    taladro = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, -5), gp_Dir(0, 0, 1)), 5.0, 220.0).Shape()
    return BRepAlgoAPI_Cut(eje, taladro).Shape()


def placa_con_agujeros():
    """Placa 200×100×20 con cuatro agujeros pasantes ø12 y uno ciego ø20."""
    placa = BRepPrimAPI_MakeBox(200.0, 100.0, 20.0).Shape()
    for x, y in ((25, 25), (175, 25), (25, 75), (175, 75)):
        broca = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(x, y, -2), gp_Dir(0, 0, 1)), 6.0, 24.0).Shape()
        placa = BRepAlgoAPI_Cut(placa, broca).Shape()
    ciego = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(100, 50, 8), gp_Dir(0, 0, 1)), 10.0, 20.0).Shape()
    return BRepAlgoAPI_Cut(placa, ciego).Shape()


def casquillo():
    """Casquillo ø60 exterior, ø40 interior, 50 de largo, con chaflán."""
    fuera = BRepPrimAPI_MakeCylinder(30.0, 50.0).Shape()
    dentro = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, -5), gp_Dir(0, 0, 1)), 20.0, 60.0).Shape()
    pieza = BRepAlgoAPI_Cut(fuera, dentro).Shape()
    try:
        ch = BRepFilletAPI_MakeChamfer(pieza)
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        exp = TopExp_Explorer(pieza, TopAbs_EDGE)
        n = 0
        while exp.More() and n < 2:
            ch.Add(1.5, TopoDS.Edge(exp.Current()))
            exp.Next(); n += 1
        return ch.Shape()
    except Exception:
        return pieza


if __name__ == "__main__":
    print("Generando piezas de prueba:")
    guardar(eje_escalonado(), "eje_escalonado.step")
    guardar(placa_con_agujeros(), "placa_agujeros.step")
    guardar(casquillo(), "casquillo.step")
