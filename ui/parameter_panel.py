"""Left-side editors for motor, loss-estimate, and operating-map settings."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_version import __version__
from calculation.characteristic_limit_resolver import (
    characteristic_input_from_legacy_motor,
)
from calculation.operating_map_grid import (
    estimate_maximum_torque_for_current,
)
from models.characteristic_input import (
    CharacteristicInput,
    CharacteristicInputMode,
)
from models.inductance_model import InductanceModel
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.saturation_map import InductanceSaturationMap
from models.winding_connection import OpenWindingTopology, WindingConnection


class CollapsibleSection(QWidget):
    """Compact disclosure section used by the left parameter panel."""

    def __init__(
        self,
        title: str,
        content: QWidget,
        *,
        expanded: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setProperty("role", "sectionHeader")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle_button.setSizePolicy(
            self.toggle_button.sizePolicy().horizontalPolicy(),
            self.toggle_button.sizePolicy().verticalPolicy(),
        )
        self.content_widget = content
        layout.addWidget(self.toggle_button)
        layout.addWidget(content)
        self.toggle_button.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(bool(expanded))
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow
            if expanded
            else Qt.ArrowType.RightArrow
        )
        self.content_widget.setVisible(bool(expanded))

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()


class OptionalNumberInput(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        minimum: float,
        maximum: float,
        decimals: int,
        suffix: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.enabled_checkbox = QCheckBox("启用")
        self.spinbox = QDoubleSpinBox()
        self.spinbox.setRange(minimum, maximum)
        self.spinbox.setDecimals(decimals)
        self.spinbox.setSuffix(suffix)
        self.spinbox.setKeyboardTracking(False)
        self.spinbox.setEnabled(False)
        layout.addWidget(self.enabled_checkbox)
        layout.addWidget(self.spinbox, 1)
        self.enabled_checkbox.toggled.connect(self.spinbox.setEnabled)
        self.enabled_checkbox.toggled.connect(self.changed)
        self.spinbox.valueChanged.connect(self.changed)

    def value(self) -> float | None:
        return self.spinbox.value() if self.enabled_checkbox.isChecked() else None

    def set_value(self, value: float | None) -> None:
        self.enabled_checkbox.setChecked(value is not None)
        if value is not None:
            self.spinbox.setValue(float(value))


class ParameterPanel(QWidget):
    calculateRequested = Signal()
    cancelRequested = Signal()
    clearCacheRequested = Signal()
    parametersChanged = Signal()
    displaySettingsChanged = Signal()
    restoreRequested = Signal()
    saveRequested = Signal()
    loadRequested = Signal()
    exportCsvRequested = Signal()
    exportMapCsvRequested = Signal()
    exportNpzRequested = Signal()
    exportExcelRequested = Signal()
    exportImagesRequested = Signal()
    importSaturationRequested = Signal()
    previewSaturationRequested = Signal()
    saveCaseRequested = Signal()
    loadCaseRequested = Signal()
    deleteCaseRequested = Signal()
    compareCasesRequested = Signal()
    exitRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(310)
        self.setMaximumWidth(430)
        self._updating = False
        self._has_result = False
        self._calculating = False
        self._ld_saturation_map: InductanceSaturationMap | None = None
        self._lq_saturation_map: InductanceSaturationMap | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root_layout.addWidget(scroll)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(6)
        scroll.setWidget(content)

        title = QLabel(f"PMSM 性能分析 v{__version__}")
        title.setProperty("role", "panelTitle")
        subtitle = QLabel("计算层：SI单位、相电流峰值、dq电压峰值")
        subtitle.setWordWrap(True)
        subtitle.setProperty("role", "muted")
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)

        motor_group = QWidget()
        motor_form = QFormLayout(motor_group)
        motor_form.setContentsMargins(8, 4, 8, 6)
        motor_form.setVerticalSpacing(4)
        self.pole_pairs = QSpinBox()
        self.pole_pairs.setRange(1, 100)
        self.rs_ohm = self._double_spin(0, 100, 6, " Ω")
        self.ld_mh = self._double_spin(1e-6, 10000, 6, " mH")
        self.lq_mh = self._double_spin(1e-6, 10000, 6, " mH")
        self.flux_pm_wb = self._double_spin(1e-6, 100, 6, " Wb")
        motor_form.addRow("极对数", self.pole_pairs)
        motor_form.addRow("定子相电阻 Rs", self.rs_ohm)
        motor_form.addRow("d轴电感 Ld", self.ld_mh)
        motor_form.addRow("q轴电感 Lq", self.lq_mh)
        motor_form.addRow("永磁体磁链", self.flux_pm_wb)
        self.inductance_model = QComboBox()
        self.inductance_model.addItem("固定 Ld/Lq", InductanceModel.CONSTANT.value)
        self.inductance_model.addItem(
            "饱和 Ld/Lq Map", InductanceModel.SATURATION_MAP.value
        )
        motor_form.addRow("电感模型", self.inductance_model)

        self.saturation_map_controls = QWidget()
        inductance_layout = QVBoxLayout(self.saturation_map_controls)
        inductance_layout.setContentsMargins(0, 2, 0, 0)
        inductance_layout.setSpacing(3)
        inductance_form = QFormLayout()
        inductance_form.setContentsMargins(0, 0, 0, 0)
        inductance_form.setVerticalSpacing(3)
        self.inductance_map_unit = QComboBox()
        self.inductance_map_unit.addItems(["μH", "mH", "H"])
        inductance_form.addRow("Map 单位", self.inductance_map_unit)
        inductance_layout.addLayout(inductance_form)
        map_buttons = QHBoxLayout()
        map_buttons.setContentsMargins(0, 0, 0, 0)
        map_buttons.setSpacing(4)
        self.import_saturation_button = QPushButton("导入 Ld/Lq Excel")
        self.preview_saturation_button = QPushButton("预览 Map")
        self.preview_saturation_button.setEnabled(False)
        map_buttons.addWidget(self.import_saturation_button)
        map_buttons.addWidget(self.preview_saturation_button)
        inductance_layout.addLayout(map_buttons)
        self.saturation_map_status = QLabel("尚未导入饱和电感 Map")
        self.saturation_map_status.setWordWrap(True)
        self.saturation_map_status.setProperty("role", "muted")
        inductance_layout.addWidget(self.saturation_map_status)
        motor_form.addRow(self.saturation_map_controls)
        self.motor_section = CollapsibleSection(
            "电机参数", motor_group, expanded=True
        )
        content_layout.addWidget(self.motor_section)

        characteristic_group = QWidget()
        characteristic_layout = QVBoxLayout(characteristic_group)
        characteristic_layout.setContentsMargins(8, 4, 8, 6)
        characteristic_layout.setSpacing(4)
        mode_form = QFormLayout()
        mode_form.setContentsMargins(0, 0, 0, 0)
        mode_form.setVerticalSpacing(4)
        self.input_mode = QComboBox()
        self.input_mode.addItem(
            "Udc + Tmax + nmax",
            CharacteristicInputMode.UDC_TMAX_NMAX.value,
        )
        self.input_mode.addItem(
            "Udc + Is_max + nmax",
            CharacteristicInputMode.UDC_IMAX_NMAX.value,
        )
        mode_form.addRow("输入方式", self.input_mode)
        self.udc_v = self._double_spin(0.001, 100000, 3, " V")
        mode_form.addRow("母线电压 Udc", self.udc_v)
        characteristic_layout.addLayout(mode_form)
        self.input_mode_pages = QStackedWidget()

        performance_page = QWidget()
        performance_form = QFormLayout(performance_page)
        performance_form.setContentsMargins(0, 0, 0, 0)
        self.target_max_torque = self._double_spin(
            0.001, 1_000_000, 3, " N·m"
        )
        performance_form.addRow("最大转矩 Tmax", self.target_max_torque)
        self.input_mode_pages.addWidget(performance_page)

        electrical_page = QWidget()
        electrical_form = QFormLayout(electrical_page)
        electrical_form.setContentsMargins(0, 0, 0, 0)
        self.max_current_vector = self._double_spin(
            0.001, 100_000, 3, " A"
        )
        electrical_form.addRow(
            "逆变器线电流 Is_max", self.max_current_vector
        )
        self.input_mode_pages.addWidget(electrical_page)
        characteristic_layout.addWidget(self.input_mode_pages)
        self.characteristic_max_speed = self._double_spin(
            1.0, 1_000_000, 1, " rpm"
        )
        speed_form = QFormLayout()
        speed_form.setContentsMargins(0, 0, 0, 0)
        speed_form.addRow("最大转速 nmax", self.characteristic_max_speed)
        characteristic_layout.addLayout(speed_form)
        self.characteristic_section = CollapsibleSection(
            "特性输入", characteristic_group, expanded=True
        )
        content_layout.addWidget(self.characteristic_section)

        winding_group = QWidget()
        winding_form = QFormLayout(winding_group)
        winding_form.setContentsMargins(8, 4, 8, 6)
        self.winding_connection = QComboBox()
        self.winding_connection.addItem("星接", WindingConnection.STAR.value)
        self.winding_connection.addItem("角接", WindingConnection.DELTA.value)
        self.winding_connection.addItem(
            "开绕组", WindingConnection.OPEN_WINDING.value
        )
        self.open_winding_topology = QComboBox()
        self.open_winding_topology.addItem(
            "双逆变器 / 共母线", OpenWindingTopology.DUAL_COMMON_DC.value
        )
        self.open_winding_topology.addItem(
            "双逆变器 / 隔离母线", OpenWindingTopology.DUAL_ISOLATED_DC.value
        )
        self.open_winding_topology.addItem(
            "自定义两侧 Udc", OpenWindingTopology.CUSTOM_DUAL_UDC.value
        )
        self.open_winding_udc2_v = self._double_spin(0.001, 100000, 3, " V")
        self.open_winding_note = QLabel(
            "电机参数按物理绕组定义；角接输入为逆变器线电流。"
        )
        self.open_winding_note.setWordWrap(True)
        self.open_winding_note.setProperty("role", "muted")
        winding_form.addRow("绕组接法", self.winding_connection)
        winding_form.addRow("开绕组拓扑", self.open_winding_topology)
        winding_form.addRow("第二侧 Udc", self.open_winding_udc2_v)
        winding_form.addRow(self.open_winding_note)
        self.winding_section = CollapsibleSection(
            "绕组 / 拓扑", winding_group, expanded=False
        )
        content_layout.addWidget(self.winding_section)

        # Attribute aliases retained for integrations that previously reached
        # into the panel.  They all reference the new canonical editors.
        self.target_max_speed = self.characteristic_max_speed
        self.scan_max_speed = self.characteristic_max_speed
        self.max_iq = self.max_current_vector

        advanced_content = QWidget()
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setContentsMargins(4, 2, 4, 4)
        advanced_layout.setSpacing(6)

        inverter_group = QGroupBox("电气与机械约束")
        inverter_form = QFormLayout(inverter_group)
        self.imax_a = self.max_current_vector
        self.id_min_a = OptionalNumberInput(
            minimum=-100000, maximum=0, decimals=3, suffix=" A"
        )
        self.pmax_kw = OptionalNumberInput(
            minimum=0.001, maximum=100000, decimals=3, suffix=" kW"
        )
        self.voltage_utilization = self._double_spin(0.001, 1.0, 4, "")
        self.modulation = QComboBox()
        self.modulation.addItems(["SVPWM", "SPWM"])
        self.current_definition = QComboBox()
        self.current_definition.addItem("峰值", "peak")
        self.current_definition.addItem("RMS", "rms")
        inverter_form.addRow("负向 Id 限制", self.id_min_a)
        inverter_form.addRow("最大机械功率", self.pmax_kw)
        inverter_form.addRow("电压利用系数", self.voltage_utilization)
        inverter_form.addRow("调制方式", self.modulation)
        inverter_form.addRow("输入电流定义", self.current_definition)
        advanced_layout.addWidget(inverter_group)

        sweep_group = QGroupBox("外特性转速扫描")
        sweep_form = QFormLayout(sweep_group)
        self.max_speed_rpm = self._double_spin(1, 1_000_000, 1, " rpm")
        self.speed_points = QSpinBox()
        self.speed_points.setRange(2, 2001)
        self._legacy_speed_label = QLabel("兼容最大机械转速")
        sweep_form.addRow(self._legacy_speed_label, self.max_speed_rpm)
        self._legacy_speed_label.hide()
        self.max_speed_rpm.hide()
        sweep_form.addRow("外特性点数", self.speed_points)
        advanced_layout.addWidget(sweep_group)

        map_group = QGroupBox("内部工况 Map")
        map_form = QFormLayout(map_group)
        self.strategy = QComboBox()
        self.strategy.addItem(
            "MTPA→弱磁→MTPV", "MTPA_FieldWeakening_MTPV"
        )
        self.strategy.addItem("最小电流", "MinimumCurrent")
        self.torque_axis_mode = QComboBox()
        self.torque_axis_mode.addItem("统一实际转矩轴", "actual")
        self.torque_axis_mode.addItem("归一化转矩比例（兼容）", "normalized")
        self.torque_axis_distribution = QComboBox()
        self.torque_axis_distribution.addItem("非均匀加密", "nonuniform")
        self.torque_axis_distribution.addItem("线性", "linear")
        self.mtpa_distance_tolerance = self._double_spin(
            0.0001, 0.5, 4, ""
        )
        self.mtpv_distance_tolerance = self._double_spin(
            0.0001, 0.5, 4, ""
        )
        self.voltage_active_threshold = self._double_spin(
            0.5, 1.0, 4, ""
        )
        self.preview_speed_points = self._integer_spin(2, 401)
        self.preview_torque_points = self._integer_spin(2, 401)
        self.full_speed_points = self._integer_spin(2, 401)
        self.full_torque_points = self._integer_spin(2, 401)
        self.grid_definition_mode = QComboBox()
        self.grid_definition_mode.addItem("按点数", "point_count")
        self.grid_definition_mode.addItem("按步长", "step")
        self.speed_step_rpm = self._double_spin(
            0.001, 1_000_000, 3, " rpm"
        )
        self.torque_step_nm = self._double_spin(
            0.001, 1_000_000, 3, " N·m"
        )
        self.grid_mode_pages = QStackedWidget()
        point_count_page = QWidget()
        point_count_form = QFormLayout(point_count_page)
        point_count_form.setContentsMargins(0, 0, 0, 0)
        point_count_form.addRow("转速点数", self.full_speed_points)
        point_count_form.addRow("转矩点数", self.full_torque_points)
        self.grid_mode_pages.addWidget(point_count_page)
        step_page = QWidget()
        step_form = QFormLayout(step_page)
        step_form.setContentsMargins(0, 0, 0, 0)
        step_form.addRow("转速步长", self.speed_step_rpm)
        step_form.addRow("转矩步长", self.torque_step_nm)
        self.grid_mode_pages.addWidget(step_page)
        self.estimated_map_points = QLabel()
        self.estimated_map_points.setProperty("role", "muted")
        self.map_maximum_speed = OptionalNumberInput(
            minimum=1, maximum=1_000_000, decimals=1, suffix=" rpm"
        )
        self.minimum_torque = self._double_spin(0, 1_000_000, 3, " N·m")
        self.include_zero_torque = QCheckBox("包含零转矩")
        self.first_quadrant_only = QCheckBox("仅第一象限（第一版固定）")
        self.first_quadrant_only.setEnabled(False)
        self.show_internal_dq = QCheckBox("dq 图显示全部内部点")
        self.diagnostic_mode = QCheckBox("诊断模式（固定 11×11）")
        self.diagnostic_mode.setToolTip(
            "仅缩小计算网格，不改变电机方程或求解策略。"
        )
        map_form.addRow("控制策略", self.strategy)
        map_form.addRow("转矩轴", self.torque_axis_mode)
        map_form.addRow("转矩轴分布", self.torque_axis_distribution)
        map_form.addRow("网格设置", self.grid_definition_mode)
        map_form.addRow(self.grid_mode_pages)
        map_form.addRow("预计工作点", self.estimated_map_points)
        map_form.addRow("Map 最大转速", self.map_maximum_speed)
        map_form.addRow("最小转矩", self.minimum_torque)
        map_form.addRow(self.include_zero_torque)
        map_form.addRow(self.first_quadrant_only)
        map_form.addRow(self.diagnostic_mode)
        self.show_internal_dq.hide()
        map_form.addRow(
            "MTPA距离阈值（高级）", self.mtpa_distance_tolerance
        )
        map_form.addRow(
            "MTPV距离阈值（高级）", self.mtpv_distance_tolerance
        )
        map_form.addRow(
            "电压激活阈值（高级）", self.voltage_active_threshold
        )
        advanced_layout.addWidget(map_group)

        loss_group = QGroupBox("损耗与效率估算")
        loss_form = QFormLayout(loss_group)
        self.iron_loss_enabled = QCheckBox("启用铁耗估算（需标定）")
        self.iron_loss_model = QComboBox()
        self.iron_loss_model.addItem("三项经验模型", "three_term")
        self.iron_loss_model.addItem("简化二项模型", "simplified")
        self.kh = self._double_spin(0, 1e12, 6, "")
        self.ke = self._double_spin(0, 1e12, 6, "")
        self.kex = self._double_spin(0, 1e12, 6, "")
        self.loss_alpha = self._double_spin(1, 4, 3, "")
        self.k1 = self._double_spin(0, 1e12, 6, "")
        self.k2 = self._double_spin(0, 1e12, 6, "")
        self.loss_model_name = QLineEdit()
        self.loss_source = QLineEdit()
        self.loss_note = QLineEdit()
        self.temperature_correction_enabled = QCheckBox("启用 Rs 温度修正")
        self.reference_temperature = self._double_spin(-100, 500, 1, " °C")
        self.winding_temperature = self._double_spin(-100, 500, 1, " °C")
        self.copper_alpha = self._double_spin(0, 0.02, 6, " /°C")
        self.minimum_efficiency_power = self._double_spin(0, 1e7, 1, " W")
        loss_form.addRow(self.iron_loss_enabled)
        loss_form.addRow("铁耗模型", self.iron_loss_model)
        loss_form.addRow("Kh", self.kh)
        loss_form.addRow("Ke", self.ke)
        loss_form.addRow("Kex", self.kex)
        loss_form.addRow("磁链指数 α", self.loss_alpha)
        loss_form.addRow("K1（简化）", self.k1)
        loss_form.addRow("K2（简化）", self.k2)
        loss_form.addRow("模型名称", self.loss_model_name)
        loss_form.addRow("系数来源", self.loss_source)
        loss_form.addRow("标定说明", self.loss_note)
        loss_form.addRow(self.temperature_correction_enabled)
        loss_form.addRow("参考温度", self.reference_temperature)
        loss_form.addRow("绕组温度", self.winding_temperature)
        loss_form.addRow("铜温度系数", self.copper_alpha)
        loss_form.addRow("效率最小输出", self.minimum_efficiency_power)
        warning = QLabel(
            "铁耗为全电机经验模型估算；默认关闭。效率不含逆变器、机械及杂散损耗。"
        )
        warning.setWordWrap(True)
        warning.setProperty("role", "muted")
        loss_form.addRow(warning)
        advanced_layout.addWidget(loss_group)

        realtime_group = QGroupBox("计算控制")
        realtime_layout = QFormLayout(realtime_group)
        self.cancel_button = QPushButton("取消当前计算")
        self.clear_cache_button = QPushButton("清除计算缓存")
        self.cancel_button.setEnabled(False)
        realtime_layout.addRow(self.cancel_button)
        realtime_layout.addRow(self.clear_cache_button)
        advanced_layout.addWidget(realtime_group)
        advanced_layout.addStretch(1)
        self.advanced_section = CollapsibleSection(
            "高级设置", advanced_content, expanded=False
        )
        content_layout.addWidget(self.advanced_section)

        case_group = QWidget()
        case_layout = QVBoxLayout(case_group)
        case_layout.setContentsMargins(8, 4, 8, 6)
        case_layout.setSpacing(4)
        self.save_case_button = QPushButton("保存当前案例")
        self.load_case_button = QPushButton("加载案例")
        self.delete_case_button = QPushButton("删除案例")
        self.compare_cases_button = QPushButton("多选对比")
        self._add_button_row(case_layout, self.save_case_button, self.load_case_button)
        self._add_button_row(case_layout, self.delete_case_button, self.compare_cases_button)
        self.case_section = CollapsibleSection(
            "案例管理", case_group, expanded=False
        )
        content_layout.addWidget(self.case_section)

        self.derived_info = QLabel()
        self.derived_info.setWordWrap(True)
        self.derived_info.setProperty("role", "derived")
        content_layout.addWidget(self.derived_info)

        self.calculate_button = QPushButton("开始计算")
        self.calculate_button.setProperty("role", "primary")
        self.restore_button = QPushButton("恢复示例参数")
        self.save_button = QPushButton("保存项目")
        self.load_button = QPushButton("加载项目")
        self.export_csv_button = QPushButton("外特性 CSV")
        self.export_map_csv_button = QPushButton("内部 Map CSV")
        self.export_npz_button = QPushButton("Map NPZ")
        self.export_excel_button = QPushButton("分析 Excel")
        self.export_images_button = QPushButton("导出图像")
        self.exit_button = QPushButton("退出")

        content_layout.addWidget(self.calculate_button)
        self._add_button_row(
            content_layout, self.restore_button, self.save_button, self.load_button
        )
        self._add_button_row(
            content_layout, self.export_csv_button, self.export_map_csv_button
        )
        self._add_button_row(
            content_layout, self.export_npz_button, self.export_excel_button
        )
        self._add_button_row(content_layout, self.export_images_button, self.exit_button)
        content_layout.addStretch(1)

        self.calculate_button.clicked.connect(self.calculateRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.clear_cache_button.clicked.connect(self.clearCacheRequested)
        self.restore_button.clicked.connect(self.restoreRequested)
        self.save_button.clicked.connect(self.saveRequested)
        self.load_button.clicked.connect(self.loadRequested)
        self.export_csv_button.clicked.connect(self.exportCsvRequested)
        self.export_map_csv_button.clicked.connect(self.exportMapCsvRequested)
        self.export_npz_button.clicked.connect(self.exportNpzRequested)
        self.export_excel_button.clicked.connect(self.exportExcelRequested)
        self.export_images_button.clicked.connect(self.exportImagesRequested)
        self.import_saturation_button.clicked.connect(
            self.importSaturationRequested
        )
        self.preview_saturation_button.clicked.connect(
            self.previewSaturationRequested
        )
        self.save_case_button.clicked.connect(self.saveCaseRequested)
        self.load_case_button.clicked.connect(self.loadCaseRequested)
        self.delete_case_button.clicked.connect(self.deleteCaseRequested)
        self.compare_cases_button.clicked.connect(self.compareCasesRequested)
        self.exit_button.clicked.connect(self.exitRequested)
        self._connect_change_signals()
        self.set_all_settings(
            MotorParameters.example_ipmsm(),
            LossModelParameters(),
            MapCalculationSettings(),
        )

    @staticmethod
    def _add_button_row(layout: QVBoxLayout, *buttons: QPushButton) -> None:
        row = QHBoxLayout()
        for button in buttons:
            row.addWidget(button)
        layout.addLayout(row)

    @staticmethod
    def _double_spin(
        minimum: float, maximum: float, decimals: int, suffix: str
    ) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setRange(minimum, maximum)
        spinbox.setDecimals(decimals)
        spinbox.setSuffix(suffix)
        spinbox.setKeyboardTracking(False)
        return spinbox

    @staticmethod
    def _integer_spin(minimum: int, maximum: int) -> QSpinBox:
        spinbox = QSpinBox()
        spinbox.setRange(minimum, maximum)
        spinbox.setKeyboardTracking(False)
        return spinbox

    def _numeric_editors(self) -> Iterable[QSpinBox | QDoubleSpinBox]:
        return (
            self.pole_pairs,
            self.rs_ohm,
            self.ld_mh,
            self.lq_mh,
            self.flux_pm_wb,
            self.udc_v,
            self.target_max_torque,
            self.max_current_vector,
            self.characteristic_max_speed,
            self.open_winding_udc2_v,
            self.voltage_utilization,
            self.max_speed_rpm,
            self.speed_points,
            self.preview_speed_points,
            self.preview_torque_points,
            self.full_speed_points,
            self.full_torque_points,
            self.speed_step_rpm,
            self.torque_step_nm,
            self.minimum_torque,
            self.mtpa_distance_tolerance,
            self.mtpv_distance_tolerance,
            self.voltage_active_threshold,
            self.kh,
            self.ke,
            self.kex,
            self.loss_alpha,
            self.k1,
            self.k2,
            self.reference_temperature,
            self.winding_temperature,
            self.copper_alpha,
            self.minimum_efficiency_power,
        )

    def _connect_change_signals(self) -> None:
        for editor in self._numeric_editors():
            editor.valueChanged.connect(self._on_input_changed)
        for optional in (self.id_min_a, self.pmax_kw, self.map_maximum_speed):
            optional.changed.connect(self._on_input_changed)
        self.diagnostic_mode.toggled.connect(self._on_input_changed)
        for combo in (
            self.input_mode,
            self.inductance_model,
            self.inductance_map_unit,
            self.winding_connection,
            self.open_winding_topology,
            self.modulation,
            self.current_definition,
            self.strategy,
            self.torque_axis_mode,
            self.torque_axis_distribution,
            self.grid_definition_mode,
            self.iron_loss_model,
        ):
            combo.currentIndexChanged.connect(self._on_input_changed)
        self.input_mode.currentIndexChanged.connect(
            self._update_input_mode_page
        )
        self.inductance_model.currentIndexChanged.connect(
            self._update_inductance_model_controls
        )
        self.winding_connection.currentIndexChanged.connect(
            self._update_winding_controls
        )
        self.open_winding_topology.currentIndexChanged.connect(
            self._update_winding_controls
        )
        self.grid_definition_mode.currentIndexChanged.connect(
            self._update_grid_mode_page
        )
        for checkbox in (
            self.include_zero_torque,
            self.first_quadrant_only,
            self.iron_loss_enabled,
            self.temperature_correction_enabled,
        ):
            checkbox.toggled.connect(self._on_input_changed)
        self.show_internal_dq.toggled.connect(self.displaySettingsChanged)
        for edit in (self.loss_model_name, self.loss_source, self.loss_note):
            edit.editingFinished.connect(self._on_input_changed)

    def _on_input_changed(self, *_args) -> None:
        self.update_derived_info()
        if not self._updating:
            self.parametersChanged.emit()

    def _update_input_mode_page(self, *_args) -> None:
        mode = CharacteristicInputMode(str(self.input_mode.currentData()))
        page = (
            0
            if mode == CharacteristicInputMode.UDC_TMAX_NMAX
            else 1
        )
        self.input_mode_pages.setCurrentIndex(page)

    def _update_grid_mode_page(self, *_args) -> None:
        self.grid_mode_pages.setCurrentIndex(
            0
            if str(self.grid_definition_mode.currentData()) == "point_count"
            else 1
        )

    def _update_inductance_model_controls(self, *_args) -> None:
        saturation = (
            str(self.inductance_model.currentData())
            == InductanceModel.SATURATION_MAP.value
        )
        self.ld_mh.setEnabled(not saturation)
        self.lq_mh.setEnabled(not saturation)
        self.saturation_map_controls.setVisible(saturation)
        self.import_saturation_button.setEnabled(saturation)
        self.preview_saturation_button.setEnabled(
            saturation
            and self._ld_saturation_map is not None
            and self._lq_saturation_map is not None
        )

    def _update_winding_controls(self, *_args) -> None:
        open_winding = (
            str(self.winding_connection.currentData())
            == WindingConnection.OPEN_WINDING.value
        )
        custom = (
            str(self.open_winding_topology.currentData())
            == OpenWindingTopology.CUSTOM_DUAL_UDC.value
        )
        self.open_winding_topology.setEnabled(open_winding)
        self.open_winding_udc2_v.setEnabled(open_winding and custom)

    def set_saturation_maps(
        self,
        ld_map: InductanceSaturationMap,
        lq_map: InductanceSaturationMap,
    ) -> None:
        if (
            ld_map.id_axis_a != lq_map.id_axis_a
            or ld_map.iq_axis_a != lq_map.iq_axis_a
        ):
            raise ValueError("Ld 与 Lq 饱和表必须使用相同 Id/Iq 网格。")
        self._ld_saturation_map = ld_map.validated()
        self._lq_saturation_map = lq_map.validated()
        rows, columns = ld_map.shape
        self.saturation_map_status.setText(
            f"已导入 {rows}×{columns}；"
            f"Id {ld_map.id_axis_a[0]:g}…{ld_map.id_axis_a[-1]:g} A；"
            f"Iq {ld_map.iq_axis_a[0]:g}…{ld_map.iq_axis_a[-1]:g} A"
        )
        self._update_inductance_model_controls()
        if not self._updating:
            self.parametersChanged.emit()

    def saturation_maps(
        self,
    ) -> tuple[InductanceSaturationMap | None, InductanceSaturationMap | None]:
        return self._ld_saturation_map, self._lq_saturation_map

    def parameters(self) -> MotorParameters:
        characteristic = self.characteristic_input()
        return MotorParameters(
            pole_pairs=self.pole_pairs.value(),
            rs_ohm=self.rs_ohm.value(),
            ld_mh=self.ld_mh.value(),
            lq_mh=self.lq_mh.value(),
            flux_pm_wb=self.flux_pm_wb.value(),
            udc_v=characteristic.dc_bus_voltage_v,
            imax_a=characteristic.max_current_vector_a,
            max_speed_rpm=characteristic.max_speed_rpm,
            speed_points=self.speed_points.value(),
            id_min_a=self.id_min_a.value(),
            pmax_kw=self.pmax_kw.value(),
            voltage_utilization=self.voltage_utilization.value(),
            modulation=self.modulation.currentText(),
            current_definition=str(self.current_definition.currentData()),
            inductance_model=InductanceModel(
                str(self.inductance_model.currentData())
            ),
            winding_connection=WindingConnection(
                str(self.winding_connection.currentData())
            ),
            open_winding_topology=OpenWindingTopology(
                str(self.open_winding_topology.currentData())
            ),
            open_winding_udc2_v=(
                self.open_winding_udc2_v.value()
                if str(self.open_winding_topology.currentData())
                == OpenWindingTopology.CUSTOM_DUAL_UDC.value
                else None
            ),
            ld_saturation_map=self._ld_saturation_map,
            lq_saturation_map=self._lq_saturation_map,
        ).validated()

    def characteristic_input(self) -> CharacteristicInput:
        return CharacteristicInput(
            input_mode=CharacteristicInputMode(
                str(self.input_mode.currentData())
            ),
            dc_bus_voltage_v=self.udc_v.value(),
            max_torque_nm=self.target_max_torque.value(),
            max_current_vector_a=self.max_current_vector.value(),
            max_speed_rpm=self.characteristic_max_speed.value(),
        ).validated()

    def loss_parameters(self) -> LossModelParameters:
        return LossModelParameters(
            iron_loss_enabled=self.iron_loss_enabled.isChecked(),
            iron_loss_model=str(self.iron_loss_model.currentData()),
            kh=self.kh.value(),
            ke=self.ke.value(),
            kex=self.kex.value(),
            alpha=self.loss_alpha.value(),
            k1=self.k1.value(),
            k2=self.k2.value(),
            model_name=self.loss_model_name.text().strip(),
            coefficient_source=self.loss_source.text().strip(),
            calibration_note=self.loss_note.text().strip(),
            reference_temperature_c=self.reference_temperature.value(),
            winding_temperature_c=self.winding_temperature.value(),
            copper_alpha_per_c=self.copper_alpha.value(),
            temperature_correction_enabled=self.temperature_correction_enabled.isChecked(),
            minimum_efficiency_output_w=self.minimum_efficiency_power.value(),
        ).validated()

    def map_settings(self) -> MapCalculationSettings:
        return MapCalculationSettings(
            preview_speed_points=self.preview_speed_points.value(),
            preview_torque_points=self.preview_torque_points.value(),
            full_speed_points=self.full_speed_points.value(),
            full_torque_points=self.full_torque_points.value(),
            grid_definition_mode=str(
                self.grid_definition_mode.currentData()
            ),
            speed_step_rpm=self.speed_step_rpm.value(),
            torque_step_nm=self.torque_step_nm.value(),
            maximum_speed_rpm=self.map_maximum_speed.value(),
            minimum_torque_nm=self.minimum_torque.value(),
            include_zero_torque=self.include_zero_torque.isChecked(),
            first_quadrant_only=self.first_quadrant_only.isChecked(),
            invalid_display="blank",
            strategy=str(self.strategy.currentData()),
            automatic_calculation=False,
            debounce_ms=500,
            show_internal_points_in_dq=self.show_internal_dq.isChecked(),
            torque_axis_mode=str(self.torque_axis_mode.currentData()),
            torque_axis_distribution=str(
                self.torque_axis_distribution.currentData()
            ),
            mtpa_distance_tolerance=(
                self.mtpa_distance_tolerance.value()
            ),
            mtpv_distance_tolerance=(
                self.mtpv_distance_tolerance.value()
            ),
            voltage_active_threshold=(
                self.voltage_active_threshold.value()
            ),
            diagnostic_mode=self.diagnostic_mode.isChecked(),
        ).validated()

    def set_parameters(self, parameters: MotorParameters) -> None:
        self.set_all_settings(
            parameters, self.loss_parameters(), self.map_settings()
        )

    def set_all_settings(
        self,
        parameters: MotorParameters,
        losses: LossModelParameters,
        settings: MapCalculationSettings,
        characteristic_input: CharacteristicInput | None = None,
    ) -> None:
        characteristic = (
            characteristic_input
            or characteristic_input_from_legacy_motor(parameters)
        ).validated()
        self._updating = True
        try:
            self.pole_pairs.setValue(parameters.pole_pairs)
            self.rs_ohm.setValue(parameters.rs_ohm)
            self.ld_mh.setValue(parameters.ld_mh)
            self.lq_mh.setValue(parameters.lq_mh)
            self.flux_pm_wb.setValue(parameters.flux_pm_wb)
            self._ld_saturation_map = parameters.ld_saturation_map
            self._lq_saturation_map = parameters.lq_saturation_map
            self.inductance_model.setCurrentIndex(
                max(
                    0,
                    self.inductance_model.findData(
                        parameters.inductance_model.value
                    ),
                )
            )
            self.winding_connection.setCurrentIndex(
                max(
                    0,
                    self.winding_connection.findData(
                        parameters.winding_connection.value
                    ),
                )
            )
            self.open_winding_topology.setCurrentIndex(
                max(
                    0,
                    self.open_winding_topology.findData(
                        parameters.open_winding_topology.value
                    ),
                )
            )
            self.open_winding_udc2_v.setValue(
                parameters.open_winding_udc2_v
                if parameters.open_winding_udc2_v is not None
                else parameters.udc_v
            )
            self.udc_v.setValue(characteristic.dc_bus_voltage_v)
            self.max_current_vector.setValue(
                characteristic.max_current_vector_a
            )
            self.max_speed_rpm.setValue(parameters.max_speed_rpm)
            self.speed_points.setValue(parameters.speed_points)
            self.id_min_a.set_value(parameters.id_min_a)
            self.pmax_kw.set_value(parameters.pmax_kw)
            self.voltage_utilization.setValue(parameters.voltage_utilization)
            self.modulation.setCurrentText(parameters.modulation)
            self.current_definition.setCurrentIndex(
                max(0, self.current_definition.findData(parameters.current_definition))
            )
            self.target_max_torque.setValue(characteristic.max_torque_nm)
            self.characteristic_max_speed.setValue(
                characteristic.max_speed_rpm
            )
            self.input_mode.setCurrentIndex(
                max(
                    0,
                    self.input_mode.findData(
                        characteristic.input_mode.value
                    ),
                )
            )
            self._update_input_mode_page()

            self.preview_speed_points.setValue(settings.preview_speed_points)
            self.preview_torque_points.setValue(settings.preview_torque_points)
            self.full_speed_points.setValue(settings.full_speed_points)
            self.full_torque_points.setValue(settings.full_torque_points)
            self.grid_definition_mode.setCurrentIndex(
                max(
                    0,
                    self.grid_definition_mode.findData(
                        settings.grid_definition_mode
                    ),
                )
            )
            self.speed_step_rpm.setValue(settings.speed_step_rpm)
            self.torque_step_nm.setValue(settings.torque_step_nm)
            self._update_grid_mode_page()
            self.map_maximum_speed.set_value(settings.maximum_speed_rpm)
            self.minimum_torque.setValue(settings.minimum_torque_nm)
            self.include_zero_torque.setChecked(settings.include_zero_torque)
            self.first_quadrant_only.setChecked(settings.first_quadrant_only)
            # Internal points are visible by default after every project load;
            # the user can still hide them explicitly after results are drawn.
            self.show_internal_dq.setChecked(True)
            self.strategy.setCurrentIndex(max(0, self.strategy.findData(settings.strategy)))
            self.torque_axis_mode.setCurrentIndex(
                max(
                    0,
                    self.torque_axis_mode.findData(
                        settings.torque_axis_mode
                    ),
                )
            )
            self.torque_axis_distribution.setCurrentIndex(
                max(
                    0,
                    self.torque_axis_distribution.findData(
                        settings.torque_axis_distribution
                    ),
                )
            )
            self.mtpa_distance_tolerance.setValue(
                settings.mtpa_distance_tolerance
            )
            self.mtpv_distance_tolerance.setValue(
                settings.mtpv_distance_tolerance
            )
            self.voltage_active_threshold.setValue(
                settings.voltage_active_threshold
            )
            self.diagnostic_mode.setChecked(settings.diagnostic_mode)

            self.iron_loss_enabled.setChecked(losses.iron_loss_enabled)
            self.iron_loss_model.setCurrentIndex(
                max(0, self.iron_loss_model.findData(losses.iron_loss_model))
            )
            self.kh.setValue(losses.kh)
            self.ke.setValue(losses.ke)
            self.kex.setValue(losses.kex)
            self.loss_alpha.setValue(losses.alpha)
            self.k1.setValue(losses.k1)
            self.k2.setValue(losses.k2)
            self.loss_model_name.setText(losses.model_name)
            self.loss_source.setText(losses.coefficient_source)
            self.loss_note.setText(losses.calibration_note)
            self.temperature_correction_enabled.setChecked(
                losses.temperature_correction_enabled
            )
            self.reference_temperature.setValue(losses.reference_temperature_c)
            self.winding_temperature.setValue(losses.winding_temperature_c)
            self.copper_alpha.setValue(losses.copper_alpha_per_c)
            self.minimum_efficiency_power.setValue(
                losses.minimum_efficiency_output_w
            )
        finally:
            self._updating = False
        if self._ld_saturation_map is not None and self._lq_saturation_map is not None:
            rows, columns = self._ld_saturation_map.shape
            self.saturation_map_status.setText(f"已加载饱和电感 Map：{rows}×{columns}")
        else:
            self.saturation_map_status.setText("尚未导入饱和电感 Map")
        self._update_inductance_model_controls()
        self._update_winding_controls()
        self.update_derived_info()

    def set_calculating(self, calculating: bool) -> None:
        self._calculating = calculating
        self.calculate_button.setEnabled(not calculating)
        self.cancel_button.setEnabled(calculating)
        self._update_calculate_button()

    def set_result_available(self, available: bool) -> None:
        self._has_result = available
        self._update_calculate_button()

    def _update_calculate_button(self) -> None:
        if self._calculating:
            text = "正在计算…"
        elif self._has_result:
            text = "重新计算"
        else:
            text = "开始计算"
        self.calculate_button.setText(text)

    def set_export_enabled(self, enabled: bool) -> None:
        for button in (
            self.export_csv_button,
            self.export_map_csv_button,
            self.export_npz_button,
            self.export_excel_button,
            self.export_images_button,
            self.save_case_button,
        ):
            button.setEnabled(enabled)

    def update_derived_info(self, *_args) -> None:
        try:
            parameters = self.parameters()
            characteristic = self.characteristic_input()
            settings = self.map_settings()
            losses = self.loss_parameters()
        except Exception:
            self.derived_info.setText("当前参数尚未通过校验")
            return
        iron_state = "已启用（估算）" if losses.iron_loss_enabled else "关闭"
        if (
            characteristic.input_mode
            == CharacteristicInputMode.UDC_TMAX_NMAX
        ):
            characteristic_text = (
                f"Udc：{characteristic.dc_bus_voltage_v:.3f} V；"
                f"Tmax：{characteristic.max_torque_nm:.3f} N·m\n"
                "Is_max将在手动计算时按MTPA反算"
            )
        else:
            current_peak = (
                characteristic.max_current_vector_a
                * parameters.current_scale_to_peak
            )
            winding_peak = (
                current_peak
                * parameters.winding_connection.line_to_winding_current_factor
            )
            characteristic_text = (
                f"Udc：{characteristic.dc_bus_voltage_v:.3f} V；"
                f"逆变器线电流峰值：{current_peak:.3f} A；"
                f"绕组dq电流峰值：{winding_peak:.3f} A"
            )
        map_maximum_speed = min(
            characteristic.max_speed_rpm,
            settings.maximum_speed_rpm
            if settings.maximum_speed_rpm is not None
            else characteristic.max_speed_rpm,
        )
        if (
            characteristic.input_mode
            == CharacteristicInputMode.UDC_TMAX_NMAX
        ):
            estimated_maximum_torque = characteristic.max_torque_nm
        else:
            estimated_maximum_torque = estimate_maximum_torque_for_current(
                parameters,
                characteristic.max_current_vector_a
                * parameters.current_scale_to_peak
                * parameters.winding_connection.line_to_winding_current_factor,
            )
        estimated_shape = settings.resolved_grid_shape(
            "full", map_maximum_speed, estimated_maximum_torque
        )
        estimated_total = estimated_shape[0] * estimated_shape[1]
        self.estimated_map_points.setText(
            f"{estimated_shape[0]} × {estimated_shape[1]} = "
            f"{estimated_total:,}"
        )
        self.derived_info.setText(
            f"识别类型：{parameters.motor_type}\n"
            f"{characteristic_text}\n"
            f"电感：{self.inductance_model.currentText()}；"
            f"接法：{self.winding_connection.currentText()}；"
            f"绕组Umax：{parameters.dq_voltage_limit_from_udc(characteristic.dc_bus_voltage_v):.3f} V\n"
            f"Map：手动全量 {estimated_shape[0]}×"
            f"{estimated_shape[1]}（预计 {estimated_total:,} 点）\n"
            f"铁耗模型：{iron_state}"
        )
