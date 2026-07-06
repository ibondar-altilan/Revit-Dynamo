# -*- coding: utf-8 -*-
import clr
import sys
import math
import time

# Подключаем стандартные формы Windows для разблокировки интерфейса Revit
clr.AddReference('System.Windows.Forms')
import System.Windows.Forms

# Импорт необходимых библиотек Revit API
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

# Импорт сервисов документа и транзакций
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Подключаем библиотеки Dynamo (RevitNodes)
clr.AddReference('RevitNodes')
import Revit
clr.ImportExtensions(Revit.Elements)

# Подключение системных коллекций .NET и Interop для окон
import System
clr.AddReference("System")
from System.Collections.Generic import List
from System.Windows.Interop import WindowInteropHelper

# Подключение библиотек интерфейса Windows (WPF)
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("System.Windows")
from System.Windows import Window, Thickness, HorizontalAlignment, SizeToContent, WindowStartupLocation
from System.Windows.Controls import StackPanel, Button, TextBlock

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

# Класс ПОЛНОСТЬЮ НЕМОДАЛЬНОГО окна с кастомным текстом под номер цепи
class NonModalConfirmationWindow(Window):
    def __init__(self, circuit_number):
        self.Title = "Подтверждение выбора трассы"
        self.Width = 450
        self.SizeToContent = SizeToContent.Height
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Topmost = True
        self.ResizeMode = sys.modules['System.Windows'].ResizeMode.NoResize
        
        panel = StackPanel()
        panel.Margin = Thickness(15)
        
        title_text = TextBlock()
        title_text.Text = f"Скорректируйте трассу цепи {circuit_number} на плане"
        title_text.FontWeight = sys.modules['System.Windows'].FontWeights.Bold
        title_text.Margin = Thickness(0, 0, 0, 5)
        panel.Children.Add(title_text)
        
        desc_text = TextBlock()
        desc_text.Text = "Используйте Ctrl чтобы добавить или Shift чтобы удалить участки цепи."
        desc_text.Margin = Thickness(0, 0, 0, 15)
        panel.Children.Add(desc_text)
        
        self.is_closed = False
        self.user_action = "Cancel"
        
        btn_apply = Button()
        btn_apply.Content = "Записать данные скорректированной трассы"
        btn_apply.Height = 35
        btn_apply.Margin = Thickness(0, 0, 0, 8)
        btn_apply.Click += self.on_apply
        panel.Children.Add(btn_apply)
        
        btn_ignore = Button()
        btn_ignore.Content = "Записать данные, вычисленные программой до корректировки"
        btn_ignore.Height = 35
        btn_ignore.Margin = Thickness(0, 0, 0, 8)
        btn_ignore.Click += self.on_ignore
        panel.Children.Add(btn_ignore)
        
        self.Content = panel

    def on_apply(self, sender, e):
        self.user_action = "ApplyCurrent"
        self.is_closed = True
        self.Close()
        
    def on_ignore(self, sender, e):
        self.user_action = "IgnoreChanges"
        self.is_closed = True
        self.Close()

    def OnClosed(self, e):
        self.is_closed = True
        Window.OnClosed(self, e)

def get_revit_element(dynamo_element):
    if not dynamo_element: return None
    if hasattr(dynamo_element, 'InternalElement'): return dynamo_element.InternalElement
    return dynamo_element

def get_parameter_value_string(element, param_name):
    param = element.LookupParameter(param_name)
    if not param or not param.HasValue: return ""
    if param.StorageType == StorageType.String: return param.AsString() or ""
    return param.AsValueString() or ""

def get_parameter_value_double(element, param_name):
    param = element.LookupParameter(param_name)
    if not param or not param.HasValue or param.StorageType != StorageType.Double: return 0.0
    return param.AsDouble()
