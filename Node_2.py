# Node 2
# Назначение:
# 1) По участкам трассы определяет целевой уровень (по геометрии Z).
# 2) Находит подходящие планы этажа этого уровня.
# 3) Возвращает выбранный целевой вид (автовыбор или выбор пользователем).

# -*- coding: utf-8 -*-
import clr
import sys

# Подключение библиотек интерфейса Windows (WPF)
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("System.Windows")
from System.Windows import Window, Thickness, HorizontalAlignment, SizeToContent, WindowStartupLocation
from System.Windows.Controls import StackPanel, Button, TextBlock

# Импорт Revit API
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

# Класс окна выбора вида (WPF - модальное)
class DynamicButtonsWindow(Window):
    def __init__(self, options_list):
        self.Title = "Выбор вида для трассы"
        self.Width = 450
        self.SizeToContent = SizeToContent.Height
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Topmost = True
        
        panel = StackPanel()
        panel.Margin = Thickness(15)
        
        title_text = TextBlock()
        title_text.Text = "Найдено несколько планов для трассы. Выберите один:"
        title_text.Margin = Thickness(0, 0, 0, 15)
        title_text.FontSize = 12
        panel.Children.Add(title_text)

        self.selected_option = None
        
        for option in options_list:
            btn = Button()
            btn.Content = str(option)
            btn.Height = 35
            btn.Margin = Thickness(0, 0, 0, 8)
            btn.HorizontalAlignment = HorizontalAlignment.Stretch
            btn.Click += self.on_button_click
            panel.Children.Add(btn)
            
        self.Content = panel

    def on_button_click(self, sender, e):
        self.selected_option = sender.Content
        self.Close()

def get_revit_element(dynamo_element):
    if not dynamo_element: return None
    if hasattr(dynamo_element, 'InternalElement'): return dynamo_element.InternalElement
    return dynamo_element

# ЖЕЛЕЗНОЕ ИСПРАВЛЕНИЕ: Получение Z БЕЗ использования нестабильного .get_BoundingBox()
def get_element_z_coordinate(element):
    loc = element.Location
    if not loc:
        return None
        
    # Сценарий А: Если это линия (LocationCurve) — берем среднюю точку между концами кривой
    if hasattr(loc, "Curve") and loc.Curve is not None:
        c = loc.Curve
        return (c.GetEndPoint(0).Z + c.GetEndPoint(1).Z) / 2.0
        
    # Сценарий Б: Если это точка (LocationPoint) — берем Z ее координат напрямую
    if hasattr(loc, "Point") and loc.Point is not None:
        return loc.Point.Z
        
    # Сценарий В: Резервный метод для FamilyInstance (извлечение базовой точки размещения .Origin)
    if hasattr(element, "Origin") and element.Origin is not None:
        return element.Origin.Z
        
    return None

# --- ШАГ 1: ПОЛУЧЕНИЕ ДАННЫХ ИЗ ПОРТОВ ---
counted_elements = IN[0]
if not counted_elements:
    raise Exception("Ошибка: На вход IN[0] не переданы элементы трассы.")

desired_view_name = ""
desired_view_id_value = None

if len(IN) > 1 and IN[1] is not None:
    raw_view_input = IN[1]
    # Распаковка списка Dynamo, если на вход IN[1] пришел массив видов
    if isinstance(raw_view_input, list) and len(raw_view_input) > 0:
        raw_view_input = raw_view_input[0]
    
    if raw_view_input:
        revit_in1 = get_revit_element(raw_view_input)
        if revit_in1 and hasattr(revit_in1, "Id") and hasattr(revit_in1, "ViewType"):
            desired_view_id_value = revit_in1.Id.IntegerValue
        elif isinstance(raw_view_input, str):
            desired_view_name = raw_view_input.strip().lower()

# --- ШАГ 2: ГЕОМЕТРИЧЕСКИЙ РАСЧЕТ УРОВНЯ ---
z_coordinates = []
for item in counted_elements:
    revit_item = get_revit_element(item)
    if revit_item:
        z_val = get_element_z_coordinate(revit_item)
        if z_val is not None: 
            z_coordinates.append(z_val)

if not z_coordinates:
    raise Exception("Ошибка: Не удалось определить геометрические координаты Z для трасс.")

level_collector = FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType()
avg_trajectory_z = sum(z_coordinates) / float(len(z_coordinates))
closest_level = None
max_level_elevation_below = -float('inf')
tolerance_feet = 0.328 

for lvl in level_collector:
    elevation = lvl.Elevation
    if elevation <= (avg_trajectory_z + tolerance_feet):
        if elevation > max_level_elevation_below:
            max_level_elevation_below = elevation
            closest_level = lvl

if not closest_level:
    raise Exception("Ошибка: Не найден уровень под отметкой трассы.")

# --- ШАГ 3: ФИЛЬТРАЦИЯ ПЛАНОВ ЭТАЖЕЙ ---
view_collector = FilteredElementCollector(doc).OfClass(ViewPlan).WhereElementIsNotElementType()
found_views = []
pre_selected_view = None 

for view in view_collector:
    if view.IsTemplate or view.ViewType != ViewType.FloorPlan: continue
    if view.GenLevel and view.GenLevel.Id == closest_level.Id:
        found_views.append(view)
        
        if desired_view_id_value is not None and view.Id.IntegerValue == desired_view_id_value:
            pre_selected_view = view
        elif desired_view_name and view.Name.strip().lower() == desired_view_name:
            pre_selected_view = view

if not found_views:
    raise Exception(f"Ошибка: Нет планов этажей для уровня '{closest_level.Name}'.")

# --- ШАГ 4: ОПРЕДЕЛЕНИЕ ЦЕЛЕВОГО ВИДА ---
target_view = None

if pre_selected_view:
    target_view = pre_selected_view
elif len(found_views) == 1:
    target_view = next(iter(found_views))
else:
    view_names = [v.Name for v in found_views]
    form = DynamicButtonsWindow(view_names)
    form.ShowDialog()
    if form.selected_option is None:
        raise Exception("Выполнение отменено пользователем.")
    for view in found_views:
        if view.Name == form.selected_option:
            target_view = view
            break

# Передаем строго один выбранный объект вида Revit в Нод 3
OUT = target_view
