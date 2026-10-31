"""
================================================================================
Limpiador y Optimizador de Disco - Edición Avanzada Multi-Unidad y USB
Desarrollada con CustomTkinter, Psutil y arquitectura multihilo asíncrona segura.
================================================================================
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import datetime
import glob
import gc
import os
import queue
import re
import stat
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import customtkinter as ctk
import psutil

# ==============================================================================
# CONFIGURACIÓN VISUAL Y DE TEMA
# ==============================================================================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

COLOR_BG_DARK = "#101216"
COLOR_CARD_BG = "#1A1D24"
COLOR_CARD_BORDER = "#2B303C"
COLOR_LOG_BG = "#0F0F0F"  # Requisito explícito: consola fondo #0F0F0F
COLOR_ACCENT_BLUE = "#2563EB"
COLOR_ACCENT_HOVER = "#1D4ED8"
COLOR_SUCCESS = "#10B981"
COLOR_SUCCESS_HOVER = "#059669"
COLOR_WARNING = "#F59E0B"
COLOR_DANGER = "#EF4444"
COLOR_DANGER_HOVER = "#DC2626"
COLOR_PURPLE = "#8B5CF6"
COLOR_PURPLE_HOVER = "#7C3AED"
COLOR_TEXT_PRIMARY = "#F3F4F6"
COLOR_TEXT_MUTED = "#9CA3AF"
COLOR_BADGE_BG = "#232731"

FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_SUBTITLE = ("Segoe UI", 11)
FONT_CARD_VAL = ("Segoe UI", 19, "bold")
FONT_CARD_LABEL = ("Segoe UI", 11, "bold")
FONT_CARD_SUB = ("Segoe UI", 10)
FONT_BUTTON = ("Segoe UI", 12, "bold")
FONT_LOG = ("Consolas", 10)

# Constantes de Win32 API
FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_SYSTEM = 0x04
FILE_ATTRIBUTE_NORMAL = 0x80
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100


# ==============================================================================
# UTILIDADES Y SISTEMA NATIVO WINDOWS
# ==============================================================================
def format_bytes(bytes_count: int | float) -> str:
    """Convierte bytes a formato legible (B, KB, MB, GB, TB)."""
    if bytes_count <= 0:
        return "0.00 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    val = float(bytes_count)
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    return f"{val:.2f} {units[unit_idx]}"


class SHQUERYRBINFO(ctypes.Structure):
    """Estructura de la API Win32 para consulta de la Papelera de Reciclaje."""
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


@dataclass
class MountedDriveInfo:
    mountpoint: str
    label: str
    fstype: str
    tag: str
    display: str
    is_usb: bool
    is_sys: bool


class WindowsSystemHelper:
    """Interacción nativa con el sistema operativo Windows y dispositivos."""

    DRIVE_TYPES = {
        0: "Desconocido",
        1: "Sin raíz",
        2: "USB",
        3: "Disco Local",
        4: "Unidad de Red",
        5: "CD-ROM",
        6: "Disco RAM",
    }

    @classmethod
    def get_mounted_drives(cls) -> List[MountedDriveInfo]:
        """Detecta todas las unidades montadas en el sistema con su letra, formato y etiqueta."""
        kernel32 = ctypes.windll.kernel32
        drives: List[MountedDriveInfo] = []

        system_drive = os.getenv("SystemDrive", "C:").upper()
        if not system_drive.endswith("\\"):
            system_drive += "\\"

        try:
            partitions = psutil.disk_partitions(all=False)
        except Exception:
            partitions = []

        for part in partitions:
            root = part.mountpoint
            if not root:
                continue

            dtype = kernel32.GetDriveTypeW(root)
            type_str = cls.DRIVE_TYPES.get(dtype, "Disco")

            vol_name = ctypes.create_unicode_buffer(1024)
            fs_name = ctypes.create_unicode_buffer(1024)
            serial = wintypes.DWORD()
            max_len = wintypes.DWORD()
            flags = wintypes.DWORD()

            res = kernel32.GetVolumeInformationW(
                root,
                vol_name,
                ctypes.sizeof(vol_name),
                ctypes.byref(serial),
                ctypes.byref(max_len),
                ctypes.byref(flags),
                fs_name,
                ctypes.sizeof(fs_name),
            )

            label = vol_name.value if res and vol_name.value else ""
            fstype = fs_name.value if res and fs_name.value else part.fstype

            is_sys = root[:2].upper() == system_drive[:2]
            is_usb = dtype == 2

            if is_sys:
                tag = "Sistema"
            elif is_usb:
                tag = "USB"
            elif "fixed" in part.opts:
                tag = "HDD/SSD"
            else:
                tag = type_str

            desc_part = f"{label} - {fstype}" if label else f"{tag} - {fstype}"
            display = f"{root} ({desc_part})"

            drives.append(
                MountedDriveInfo(
                    mountpoint=root,
                    label=label,
                    fstype=fstype,
                    tag=tag,
                    display=display,
                    is_usb=is_usb,
                    is_sys=is_sys,
                )
            )

        if not drives:
            drives.append(
                MountedDriveInfo(
                    mountpoint="C:\\",
                    label="Sistema",
                    fstype="NTFS",
                    tag="Sistema",
                    display="C:\\ (Sistema - NTFS)",
                    is_usb=False,
                    is_sys=True,
                )
            )

        return drives

    @staticmethod
    def get_recycle_bin_stats() -> Tuple[int, int]:
        """Obtiene tamaño en bytes y cantidad de elementos en la papelera de reciclaje."""
        try:
            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            hresult = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
            if hresult == 0:
                return max(0, int(info.i64Size)), max(0, int(info.i64NumItems))
        except Exception:
            pass
        return 0, 0

    @staticmethod
    def empty_recycle_bin() -> bool:
        """Vacía la papelera de reciclaje silenciosamente vía Win32 Shell API."""
        try:
            flags = 0x00000001 | 0x00000002 | 0x00000004
            res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
            return res == 0
        except Exception:
            return False

    @staticmethod
    def get_disk_status(drive: Optional[str] = None) -> Dict[str, any]:
        """Consulta métricas de disco utilizando psutil."""
        if not drive:
            drive = os.getenv("SystemDrive", "C:") + "\\"
        try:
            usage = psutil.disk_usage(drive)
            return {
                "drive": drive,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            }
        except Exception:
            return {
                "drive": drive,
                "total": 1,
                "used": 0,
                "free": 1,
                "percent": 0.0,
            }

    @staticmethod
    def optimize_ram() -> Tuple[int, int, any]:
        """
        Libera memoria RAM reduciendo el conjunto de trabajo (Working Set)
        de los procesos accesibles y ejecutando recolección de basura.
        """
        gc.collect()

        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.restype = wintypes.BOOL

        before_mem = psutil.virtual_memory()

        # Recortar memoria del proceso actual
        curr_proc = kernel32.GetCurrentProcess()
        psapi.EmptyWorkingSet(curr_proc)

        trimmed_processes = 0
        for proc in psutil.process_iter(["pid"]):
            pid = proc.info["pid"]
            if pid <= 4:
                continue
            try:
                h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if h_proc:
                    if psapi.EmptyWorkingSet(h_proc):
                        trimmed_processes += 1
                    kernel32.CloseHandle(h_proc)
            except Exception:
                pass

        after_mem = psutil.virtual_memory()
        freed_bytes = max(0, before_mem.used - after_mem.used)
        return freed_bytes, trimmed_processes, after_mem

    @staticmethod
    def is_suspicious_or_broken_shortcut(lnk_path: str, is_usb: bool = False) -> Tuple[bool, str]:
        """
        Analiza archivos .lnk para identificar accesos directos maliciosos (virus USB)
        o accesos dañados hacia rutas inexistentes.
        """
        try:
            with open(lnk_path, "rb") as f:
                content = f.read(8192)

            # Detectar comandos de ejecución de malware típicos en gusanos USB
            malicious_patterns = [
                b"cmd.exe",
                b"powershell",
                b"wscript",
                b"cscript",
                b"rundll32",
                b"mshta",
                b"regsvr32",
            ]

            content_lower = content.lower()
            for pat in malicious_patterns:
                if pat in content_lower or pat.decode("ascii").encode("utf-16le").lower() in content_lower:
                    return True, "Acceso malicioso que invoca intérprete de comandos (Virus USB)"

            # Detectar si el destino apuntado en el binario ya no existe
            match = re.search(rb"[a-zA-Z]:\\[a-zA-Z0-9_\-\.\\]+", content)
            if match:
                target_path = match.group(0).decode("latin-1", errors="ignore").rstrip("\x00")
                if not os.path.exists(target_path):
                    return True, f"Ruta destino inexistente: {target_path}"

            # En USBs, accesos directos en raíz suelen ser máscaras de virus
            if is_usb and os.path.dirname(lnk_path).rstrip("\\") == os.path.splitdrive(lnk_path)[0]:
                return True, "Acceso directo en raíz de USB sospechoso"

        except Exception:
            pass
        return False, ""

    @staticmethod
    def unhide_masked_directory(dir_path: str) -> bool:
        """Quita atributos oculto y sistema a carpetas enmascaradas por virus en memorias USB."""
        try:
            kernel32 = ctypes.windll.kernel32
            attrs = kernel32.GetFileAttributesW(dir_path)
            if attrs != -1 and (attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)):
                new_attrs = attrs & ~(FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)
                if new_attrs == 0:
                    new_attrs = FILE_ATTRIBUTE_NORMAL
                return bool(kernel32.SetFileAttributesW(dir_path, new_attrs))
        except Exception:
            pass
        return False


# ==============================================================================
# MODELOS DE DATOS Y REGISTRO DE CATEGORÍAS
# ==============================================================================
@dataclass
class TargetFileItem:
    path: str
    size: int
    category_id: str
    is_dir: bool = False
    is_unmask_target: bool = False
    mtime: float = 0.0


@dataclass
class CategoryScanResult:
    category_id: str
    items: List[TargetFileItem] = field(default_factory=list)
    total_bytes: int = 0
    item_count: int = 0
    access_denied_count: int = 0


class CleaningCategoryRegistry:
    """Definición y resolución de rutas dinámicas adaptadas a discos internos y externos/USB."""

    CAT_TEMP = "temp"
    CAT_BROWSER = "browser"
    CAT_DOWNLOADS = "downloads"
    CAT_RECYCLE = "recycle"
    CAT_LARGE_FILES = "large_files"
    CAT_EMPTY_DIRS = "empty_dirs"
    CAT_USB_DISINFECT = "usb_disinfect"

    @classmethod
    def get_definitions(cls) -> List[Dict[str, any]]:
        return [
            {
                "id": cls.CAT_TEMP,
                "title": "Archivos temporales del sistema (%TEMP%)",
                "desc": "Archivos temporales generados por Windows, instaladores y software en ejecución.",
                "icon": "⚡",
            },
            {
                "id": cls.CAT_BROWSER,
                "title": "Caché de navegadores (Chrome / Edge / Firefox)",
                "desc": "Caché de navegación, archivos residuales y scripts en Chrome, Edge, Firefox y Brave.",
                "icon": "🌐",
            },
            {
                "id": cls.CAT_DOWNLOADS,
                "title": "Archivos de descargas incompletas (.tmp, .crdownload)",
                "desc": "Fragmentos y descargas incompletas (.crdownload, .part, .tmp, .partial) en Descargas.",
                "icon": "📥",
            },
            {
                "id": cls.CAT_RECYCLE,
                "title": "Caché de la papelera / archivos residuales",
                "desc": "Papelera de reciclaje de Windows, volcados de memoria (CrashDumps) e informes de error WER.",
                "icon": "🗑️",
            },
            {
                "id": cls.CAT_LARGE_FILES,
                "title": "Archivos Pesados (> 200 MB)",
                "desc": "Detecta archivos mayores a 200 MB en la unidad seleccionada para revisión detallada.",
                "icon": "🔍",
            },
            {
                "id": cls.CAT_EMPTY_DIRS,
                "title": "Carpetas Vacías",
                "desc": "Identifica y elimina directorios sin contenido ni subarchivos en la unidad seleccionada.",
                "icon": "📁",
            },
            {
                "id": cls.CAT_USB_DISINFECT,
                "title": "Desinfección USB / Accesos Directos",
                "desc": "Elimina accesos directos maliciosos (.lnk), scripts autorun y desoculta carpetas infectadas.",
                "icon": "🛡️",
            },
        ]


# ==============================================================================
# MOTORES ASÍNCRONOS DE ESCANEO Y LIMPIEZA
# ==============================================================================
class ScannerWorker(threading.Thread):
    """
    Hilo de escaneo: recorre directorios objetivo, detecta archivos pesados (>200MB),
    carpetas vacías, malware USB y caché del sistema.
    """

    def __init__(
        self,
        selected_categories: List[str],
        selected_drive: str,
        event_queue: queue.Queue,
        cancel_event: threading.Event,
    ):
        super().__init__(daemon=True)
        self.selected_categories = selected_categories
        self.selected_drive = selected_drive
        self.event_queue = event_queue
        self.cancel_event = cancel_event

    def _log(self, msg: str, level: str = "INFO"):
        self.event_queue.put(("LOG", (msg, level)))

    def run(self):
        self._log(f"[INICIO] Iniciando análisis exhaustivo en unidad: {self.selected_drive}...", "INFO")
        start_time = time.time()
        results: Dict[str, CategoryScanResult] = {}
        total_found_bytes = 0
        total_found_items = 0

        is_system_drive = self.selected_drive[:2].upper() == os.getenv("SystemDrive", "C:")[:2].upper()
        incomplete_extensions = {".crdownload", ".part", ".tmp", ".download", ".partial"}

        # ----------------------------------------------------------------------
        # 1. ARCHIVOS TEMPORALES
        # ----------------------------------------------------------------------
        if CleaningCategoryRegistry.CAT_TEMP in self.selected_categories:
            if not self.cancel_event.is_set():
                cat_id = CleaningCategoryRegistry.CAT_TEMP
                self.event_queue.put(("STATUS", "Analizando archivos temporales..."))
                res = CategoryScanResult(category_id=cat_id)

                temp_paths = []
                if is_system_drive:
                    user_temp = os.environ.get("TEMP")
                    if user_temp and os.path.isdir(user_temp):
                        temp_paths.append(user_temp)
                    local_temp = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp")
                    if local_temp and os.path.isdir(local_temp) and local_temp.lower() != (user_temp or "").lower():
                        temp_paths.append(local_temp)
                    win_temp = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Temp")
                    if os.path.isdir(win_temp):
                        temp_paths.append(win_temp)
                else:
                    d_temp = os.path.join(self.selected_drive, "Temp")
                    if os.path.isdir(d_temp):
                        temp_paths.append(d_temp)

                for r_path in temp_paths:
                    if self.cancel_event.is_set():
                        break
                    for cur_dir, dirs, files in os.walk(r_path, topdown=True, onerror=None):
                        if self.cancel_event.is_set():
                            break
                        for fname in files:
                            fp = os.path.join(cur_dir, fname)
                            try:
                                sz = os.stat(fp, follow_symlinks=False).st_size
                                res.items.append(TargetFileItem(path=fp, size=sz, category_id=cat_id))
                                res.total_bytes += sz
                                res.item_count += 1
                            except (PermissionError, OSError):
                                res.access_denied_count += 1

                results[cat_id] = res
                total_found_bytes += res.total_bytes
                total_found_items += res.item_count
                self._log(f"[TEMPORALES] {res.item_count:,} archivos listos ({format_bytes(res.total_bytes)})", "SUCCESS")

        # ----------------------------------------------------------------------
        # 2. CACHÉ DE NAVEGADORES
        # ----------------------------------------------------------------------
        if CleaningCategoryRegistry.CAT_BROWSER in self.selected_categories and not self.cancel_event.is_set():
            cat_id = CleaningCategoryRegistry.CAT_BROWSER
            self.event_queue.put(("STATUS", "Analizando caché de navegadores web..."))
            res = CategoryScanResult(category_id=cat_id)

            browser_dirs = []
            local_app = os.environ.get("LOCALAPPDATA", "")

            # Chrome
            chrome_base = os.path.join(local_app, "Google", "Chrome", "User Data")
            if os.path.isdir(chrome_base):
                for p in ["Default/Cache", "Default/Code Cache", "Default/GPUCache", "Profile */Cache"]:
                    browser_dirs.extend(glob.glob(os.path.join(chrome_base, p)))

            # Edge
            edge_base = os.path.join(local_app, "Microsoft", "Edge", "User Data")
            if os.path.isdir(edge_base):
                for p in ["Default/Cache", "Default/Code Cache", "Default/GPUCache", "Profile */Cache"]:
                    browser_dirs.extend(glob.glob(os.path.join(edge_base, p)))

            # Firefox
            firefox_profiles = os.path.join(local_app, "Mozilla", "Firefox", "Profiles")
            if os.path.isdir(firefox_profiles):
                for p in ["*/cache2", "*/startupCache"]:
                    browser_dirs.extend(glob.glob(os.path.join(firefox_profiles, p)))

            # Brave
            brave_base = os.path.join(local_app, "BraveSoftware", "Brave-Browser", "User Data")
            if os.path.isdir(brave_base):
                for p in ["Default/Cache", "Default/Code Cache"]:
                    browser_dirs.extend(glob.glob(os.path.join(brave_base, p)))

            for b_dir in [d for d in browser_dirs if os.path.isdir(d)]:
                if self.cancel_event.is_set():
                    break
                for cur_dir, dirs, files in os.walk(b_dir, topdown=True, onerror=None):
                    if self.cancel_event.is_set():
                        break
                    for fname in files:
                        fp = os.path.join(cur_dir, fname)
                        try:
                            sz = os.stat(fp, follow_symlinks=False).st_size
                            res.items.append(TargetFileItem(path=fp, size=sz, category_id=cat_id))
                            res.total_bytes += sz
                            res.item_count += 1
                        except (PermissionError, OSError):
                            res.access_denied_count += 1

            results[cat_id] = res
            total_found_bytes += res.total_bytes
            total_found_items += res.item_count
            self._log(f"[NAVEGADORES] {res.item_count:,} archivos en caché ({format_bytes(res.total_bytes)})", "SUCCESS")

        # ----------------------------------------------------------------------
        # 3. DESCARGAS INCOMPLETAS
        # ----------------------------------------------------------------------
        if CleaningCategoryRegistry.CAT_DOWNLOADS in self.selected_categories and not self.cancel_event.is_set():
            cat_id = CleaningCategoryRegistry.CAT_DOWNLOADS
            self.event_queue.put(("STATUS", "Analizando descargas incompletas..."))
            res = CategoryScanResult(category_id=cat_id)

            dl_paths = [os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")]
            if not is_system_drive:
                ext_dl = os.path.join(self.selected_drive, "Downloads")
                if os.path.isdir(ext_dl):
                    dl_paths.append(ext_dl)

            for dl_dir in dl_paths:
                if not os.path.isdir(dl_dir):
                    continue
                try:
                    with os.scandir(dl_dir) as entries:
                        for entry in entries:
                            if self.cancel_event.is_set():
                                break
                            try:
                                if entry.is_file(follow_symlinks=False):
                                    ext = os.path.splitext(entry.name)[1].lower()
                                    if ext in incomplete_extensions:
                                        mtime = entry.stat().st_mtime
                                        if time.time() - mtime < 45:
                                            self._log(f"[OMITIDO - DESCARGA ACTIVA] En curso: {entry.name}", "WARN")
                                            continue
                                        sz = entry.stat().st_size
                                        res.items.append(TargetFileItem(path=entry.path, size=sz, category_id=cat_id))
                                        res.total_bytes += sz
                                        res.item_count += 1
                                        self._log(f"[DETECTADO] Descarga incompleta: {entry.name} ({format_bytes(sz)})", "INFO")
                            except (PermissionError, OSError):
                                res.access_denied_count += 1
                except (PermissionError, OSError):
                    pass

            results[cat_id] = res
            total_found_bytes += res.total_bytes
            total_found_items += res.item_count
            self._log(f"[DESCARGAS] {res.item_count} descargas incompletas ({format_bytes(res.total_bytes)})", "SUCCESS")

        # ----------------------------------------------------------------------
        # 4. PAPELERA Y RESIDUALES
        # ----------------------------------------------------------------------
        if CleaningCategoryRegistry.CAT_RECYCLE in self.selected_categories and not self.cancel_event.is_set():
            cat_id = CleaningCategoryRegistry.CAT_RECYCLE
            self.event_queue.put(("STATUS", "Consultando papelera de reciclaje y residuales..."))
            res = CategoryScanResult(category_id=cat_id)

            rb_size, rb_items = WindowsSystemHelper.get_recycle_bin_stats()
            if rb_items > 0:
                res.total_bytes += rb_size
                res.item_count += rb_items
                res.items.append(
                    TargetFileItem(
                        path="[Papelera de reciclaje de Windows]",
                        size=rb_size,
                        category_id=cat_id,
                    )
                )

            # Volcados de depuración
            crash_dumps = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrashDumps")
            if os.path.isdir(crash_dumps):
                for cur_dir, dirs, files in os.walk(crash_dumps):
                    for fname in files:
                        fp = os.path.join(cur_dir, fname)
                        try:
                            sz = os.stat(fp).st_size
                            res.items.append(TargetFileItem(path=fp, size=sz, category_id=cat_id))
                            res.total_bytes += sz
                            res.item_count += 1
                        except Exception:
                            pass

            results[cat_id] = res
            total_found_bytes += res.total_bytes
            total_found_items += res.item_count
            self._log(f"[PAPELERA/RESIDUALES] {res.item_count} elementos ({format_bytes(res.total_bytes)})", "SUCCESS")

        # ----------------------------------------------------------------------
        # 5. EXPLORACIÓN PROFUNDA DE LA UNIDAD (Pesados, Carpetas Vacías, USB)
        # ----------------------------------------------------------------------
        needs_drive_walk = any(
            c in self.selected_categories
            for c in [
                CleaningCategoryRegistry.CAT_LARGE_FILES,
                CleaningCategoryRegistry.CAT_EMPTY_DIRS,
                CleaningCategoryRegistry.CAT_USB_DISINFECT,
            ]
        )

        if needs_drive_walk and not self.cancel_event.is_set():
            large_res = CategoryScanResult(category_id=CleaningCategoryRegistry.CAT_LARGE_FILES)
            empty_res = CategoryScanResult(category_id=CleaningCategoryRegistry.CAT_EMPTY_DIRS)
            usb_res = CategoryScanResult(category_id=CleaningCategoryRegistry.CAT_USB_DISINFECT)

            scan_large = CleaningCategoryRegistry.CAT_LARGE_FILES in self.selected_categories
            scan_empty = CleaningCategoryRegistry.CAT_EMPTY_DIRS in self.selected_categories
            scan_usb = CleaningCategoryRegistry.CAT_USB_DISINFECT in self.selected_categories

            # Determinar directorios a examinar
            roots_to_scan = []
            skip_dirs = {
                "$recycle.bin",
                "system volume information",
                ".git",
                "node_modules",
                "__pycache__",
                ".gemini",
                "site-packages",
            }
            if is_system_drive:
                # En C: priorizar perfil de usuario y carpetas de datos para agilidad y seguridad
                user_prof = os.environ.get("USERPROFILE", "C:\\Users")
                roots_to_scan = [user_prof]
                skip_dirs.update({"windows", "program files", "program files (x86)", "appdata\\local\\microsoft"})
            else:
                roots_to_scan = [self.selected_drive]

            script_extensions = {".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".bat", ".cmd"}
            kernel32 = ctypes.windll.kernel32

            last_tick = time.time()

            for scan_root in roots_to_scan:
                if self.cancel_event.is_set():
                    break
                if not os.path.exists(scan_root):
                    continue

                self.event_queue.put(("STATUS", f"Explorando unidad: {scan_root}..."))

                for current_dir, dirs, files in os.walk(scan_root, topdown=True, onerror=None):
                    if self.cancel_event.is_set():
                        break

                    # Excluir directorios protegidos del sistema
                    dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]

                    # 1. Detección de carpetas vacías
                    if scan_empty and not dirs and not files:
                        empty_res.items.append(
                            TargetFileItem(
                                path=current_dir,
                                size=0,
                                category_id=CleaningCategoryRegistry.CAT_EMPTY_DIRS,
                                is_dir=True,
                            )
                        )
                        empty_res.item_count += 1

                    # 2. Detección de carpetas ocultas por virus (desinfección USB)
                    if scan_usb and not is_system_drive:
                        for dname in list(dirs):
                            dir_full = os.path.join(current_dir, dname)
                            try:
                                attrs = kernel32.GetFileAttributesW(dir_full)
                                if attrs != -1 and (attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)):
                                    usb_res.items.append(
                                        TargetFileItem(
                                            path=dir_full,
                                            size=0,
                                            category_id=CleaningCategoryRegistry.CAT_USB_DISINFECT,
                                            is_dir=True,
                                            is_unmask_target=True,
                                        )
                                    )
                                    usb_res.item_count += 1
                                    self._log(f"[USB INFECTADA] Carpeta oculta por virus detectada: {dir_full}", "WARN")
                            except Exception:
                                pass

                    # 3. Inspección archivo por archivo
                    for fname in files:
                        file_path = os.path.join(current_dir, fname)
                        try:
                            st = os.stat(file_path, follow_symlinks=False)
                            sz = st.st_size

                            # Detección de archivos pesados (> 200 MB)
                            if scan_large and sz >= 200 * 1024 * 1024:
                                large_res.items.append(
                                    TargetFileItem(
                                        path=file_path,
                                        size=sz,
                                        category_id=CleaningCategoryRegistry.CAT_LARGE_FILES,
                                        mtime=st.st_mtime,
                                    )
                                )
                                large_res.total_bytes += sz
                                large_res.item_count += 1
                                self._log(f"[PESADO >200MB] {fname} ({format_bytes(sz)})", "WARN")

                            # Desinfección USB / Accesos directos
                            if scan_usb:
                                fl_lower = fname.lower()
                                ext_lower = os.path.splitext(fl_lower)[1]

                                # Scripts autorun en raíz o ejecutables sospechosos
                                is_root = os.path.dirname(file_path).rstrip("\\") == self.selected_drive.rstrip("\\")
                                if fl_lower == "autorun.inf" or (is_root and ext_lower in script_extensions):
                                    usb_res.items.append(
                                        TargetFileItem(
                                            path=file_path,
                                            size=sz,
                                            category_id=CleaningCategoryRegistry.CAT_USB_DISINFECT,
                                        )
                                    )
                                    usb_res.total_bytes += sz
                                    usb_res.item_count += 1
                                    self._log(f"[USB VIRUS/AUTORUN] Script detectado: {fname}", "DANGER")

                                # Accesos directos (.lnk) dañados o maliciosos
                                elif ext_lower == ".lnk":
                                    is_mal, reason = WindowsSystemHelper.is_suspicious_or_broken_shortcut(
                                        file_path, is_usb=not is_system_drive
                                    )
                                    if is_mal:
                                        usb_res.items.append(
                                            TargetFileItem(
                                                path=file_path,
                                                size=sz,
                                                category_id=CleaningCategoryRegistry.CAT_USB_DISINFECT,
                                            )
                                        )
                                        usb_res.total_bytes += sz
                                        usb_res.item_count += 1
                                        self._log(f"[ACCESO DIRECTO DAÑADO/VIRUS] {fname}: {reason}", "WARN")

                        except (PermissionError, OSError):
                            pass

                    # Emisión de progreso amortiguada
                    now = time.time()
                    if now - last_tick > 0.15:
                        last_tick = now
                        self.event_queue.put(
                            (
                                "SCAN_TICK",
                                (
                                    f"Analizando: {os.path.basename(current_dir)}",
                                    total_found_bytes + large_res.total_bytes,
                                    total_found_items + large_res.item_count,
                                ),
                            )
                        )

            if scan_large:
                results[CleaningCategoryRegistry.CAT_LARGE_FILES] = large_res
                total_found_bytes += large_res.total_bytes
                total_found_items += large_res.item_count
                self._log(
                    f"[ARCHIVOS PESADOS] {large_res.item_count} archivos > 200MB ({format_bytes(large_res.total_bytes)})",
                    "SUCCESS",
                )

            if scan_empty:
                results[CleaningCategoryRegistry.CAT_EMPTY_DIRS] = empty_res
                total_found_items += empty_res.item_count
                self._log(f"[CARPETAS VACÍAS] {empty_res.item_count} directorios vacíos detectados", "SUCCESS")

            if scan_usb:
                results[CleaningCategoryRegistry.CAT_USB_DISINFECT] = usb_res
                total_found_bytes += usb_res.total_bytes
                total_found_items += usb_res.item_count
                self._log(
                    f"[DESINFECCIÓN USB] {usb_res.item_count} elementos (amenazas, accesos dañados y carpetas a desocultar)",
                    "SUCCESS",
                )

        if self.cancel_event.is_set():
            self._log("[CANCELADO] Análisis detenido por el usuario.", "WARN")
            self.event_queue.put(("SCAN_ABORTED", None))
            return

        elapsed = time.time() - start_time
        self.event_queue.put(
            (
                "SCAN_COMPLETE",
                (results, total_found_bytes, total_found_items, elapsed),
            )
        )
        self._log(
            f"[ÉXITO] Análisis finalizado en {elapsed:.2f}s. Total recuperable: {format_bytes(total_found_bytes)} en {total_found_items:,} elementos.",
            "SUCCESS",
        )


class CleanerWorker(threading.Thread):
    """
    Hilo de limpieza: elimina archivos de forma segura, suprime carpetas vacías,
    limpia virus USB y restaura carpetas ocultadas por malware.
    """

    def __init__(
        self,
        scan_results: Dict[str, CategoryScanResult],
        selected_categories: List[str],
        clean_large_files: bool,
        event_queue: queue.Queue,
        cancel_event: threading.Event,
    ):
        super().__init__(daemon=True)
        self.scan_results = scan_results
        self.selected_categories = selected_categories
        self.clean_large_files = clean_large_files
        self.event_queue = event_queue
        self.cancel_event = cancel_event

    def _log(self, msg: str, level: str = "INFO"):
        self.event_queue.put(("LOG", (msg, level)))

    def run(self):
        self._log("[INICIO] Iniciando proceso de optimización, desinfección y limpieza...", "INFO")
        start_time = time.time()

        total_freed_bytes = 0
        total_deleted_files = 0
        total_deleted_dirs = 0
        total_unmasked_dirs = 0
        total_skipped_in_use = 0
        total_skipped_permission = 0
        total_other_errors = 0

        items_to_process: List[TargetFileItem] = []
        has_recycle_bin = False

        for cat_id in self.selected_categories:
            if cat_id not in self.scan_results:
                continue

            # Si son archivos pesados y el usuario decidió no borrarlos, omitir
            if cat_id == CleaningCategoryRegistry.CAT_LARGE_FILES and not self.clean_large_files:
                self._log("[OMITIDO] Archivos pesados conservados para revisión.", "INFO")
                continue

            cat_res = self.scan_results[cat_id]
            for item in cat_res.items:
                if item.path == "[Papelera de reciclaje de Windows]":
                    has_recycle_bin = True
                else:
                    items_to_process.append(item)

        total_steps = len(items_to_process) + (1 if has_recycle_bin else 0)
        current_step = 0

        # 1. Vaciar papelera de reciclaje nativa
        if has_recycle_bin and not self.cancel_event.is_set():
            current_step += 1
            self.event_queue.put(("STATUS", "Vaciando Papelera de Reciclaje de Windows..."))
            self.event_queue.put(("PROGRESS", (current_step, total_steps)))

            cat_res = self.scan_results.get(CleaningCategoryRegistry.CAT_RECYCLE)
            rb_original_size = 0
            if cat_res:
                for itm in cat_res.items:
                    if itm.path == "[Papelera de reciclaje de Windows]":
                        rb_original_size = itm.size

            if WindowsSystemHelper.empty_recycle_bin():
                total_freed_bytes += rb_original_size
                total_deleted_files += 1
                self._log(
                    f"[PAPELERA VACIADA] Se liberaron {format_bytes(rb_original_size)} de la Papelera de Reciclaje.",
                    "SUCCESS",
                )
            else:
                self._log("[OMITIDO] No fue posible vaciar la papelera o ya se encontraba vacía.", "WARN")

        # Separar elementos por tipo de acción
        empty_dir_items = [it for it in items_to_process if it.is_dir and not it.is_unmask_target]
        unmask_items = [it for it in items_to_process if it.is_unmask_target]
        file_items = [it for it in items_to_process if not it.is_dir]

        # 2. Desocultar carpetas infectadas por malware USB
        for itm in unmask_items:
            if self.cancel_event.is_set():
                break
            current_step += 1
            if WindowsSystemHelper.unhide_masked_directory(itm.path):
                total_unmasked_dirs += 1
                self._log(f"[DESOCULTADA ✓] Carpeta restaurada con éxito: {itm.path}", "SUCCESS")
            else:
                self._log(f"[AVISO] No se pudo cambiar atributos a: {itm.path}", "WARN")

        # 3. Eliminar archivos regulares
        for item in file_items:
            if self.cancel_event.is_set():
                self._log("[CANCELADO] Limpieza detenida por el usuario.", "WARN")
                self.event_queue.put(("CLEAN_ABORTED", None))
                return

            current_step += 1
            if current_step % 20 == 0 or current_step == total_steps:
                self.event_queue.put(("PROGRESS", (current_step, total_steps)))
                self.event_queue.put(
                    ("STATUS", f"Eliminando ({current_step}/{total_steps}): {os.path.basename(item.path)}")
                )

            file_path = item.path
            if not os.path.exists(file_path):
                continue

            try:
                # Retirar atributo de solo lectura si está presente
                try:
                    os.chmod(file_path, stat.S_IWRITE)
                except Exception:
                    pass

                os.remove(file_path)
                total_freed_bytes += item.size
                total_deleted_files += 1

                if item.size > 20 * 1024 * 1024 or total_deleted_files % 30 == 0:
                    self._log(f"[ELIMINADO] {os.path.basename(file_path)} ({format_bytes(item.size)})", "DELETE")

            except PermissionError as e:
                winerr = getattr(e, "winerror", None)
                if winerr == 32:
                    total_skipped_in_use += 1
                    self._log(f"[OMITIDO - EN USO] Archivo bloqueado por otro proceso: {file_path}", "SKIP")
                elif winerr == 5:
                    total_skipped_permission += 1
                    self._log(f"[OMITIDO - PERMISO DENEGADO] Requiere permisos de Administrador: {file_path}", "SKIP")
                else:
                    total_other_errors += 1
                    self._log(f"[OMITIDO - ERROR PERMISO] {os.path.basename(file_path)}", "SKIP")

            except OSError as e:
                winerr = getattr(e, "winerror", None)
                if winerr == 32:
                    total_skipped_in_use += 1
                    self._log(f"[OMITIDO - EN USO] Archivo bloqueado por el sistema: {file_path}", "SKIP")
                else:
                    total_other_errors += 1
                    self._log(f"[OMITIDO - ERROR SO] {os.path.basename(file_path)}: {e.strerror}", "SKIP")

            except Exception as e:
                total_other_errors += 1
                self._log(f"[OMITIDO - ERROR INESPERADO] {os.path.basename(file_path)}: {str(e)}", "ERROR")

        # 4. Eliminar carpetas vacías (de más profunda a más externa)
        sorted_empty_dirs = sorted(empty_dir_items, key=lambda x: len(x.path), reverse=True)
        for d_item in sorted_empty_dirs:
            if self.cancel_event.is_set():
                break
            current_step += 1
            dir_p = d_item.path
            try:
                if os.path.isdir(dir_p) and not os.listdir(dir_p):
                    os.rmdir(dir_p)
                    total_deleted_dirs += 1
                    self._log(f"[CARPETA ELIMINADA] Carpeta vacía suprimida: {dir_p}", "DELETE")
            except Exception:
                pass

        elapsed = time.time() - start_time
        summary_data = {
            "freed_bytes": total_freed_bytes,
            "deleted_files": total_deleted_files,
            "deleted_dirs": total_deleted_dirs,
            "unmasked_dirs": total_unmasked_dirs,
            "skipped_in_use": total_skipped_in_use,
            "skipped_permission": total_skipped_permission,
            "other_errors": total_other_errors,
            "elapsed": elapsed,
        }

        self.event_queue.put(("CLEAN_COMPLETE", summary_data))
        self._log(
            f"[ÉXITO TOTAL] Limpieza finalizada en {elapsed:.2f}s. "
            f"Espacio liberado: {format_bytes(total_freed_bytes)} | "
            f"Archivos eliminados: {total_deleted_files:,} | "
            f"Carpetas vacías: {total_deleted_dirs} | "
            f"Carpetas desocultadas: {total_unmasked_dirs} | "
            f"Archivos en uso omitidos: {total_skipped_in_use}",
            "SUCCESS",
        )


# ==============================================================================
# VENTANA MODAL PARA REVISIÓN DE ARCHIVOS PESADOS
# ==============================================================================
class LargeFilesReviewDialog(ctk.CTkToplevel):
    """Ventana para revisar detalladamente archivos mayores a 200 MB."""

    def __init__(self, master, items: List[TargetFileItem]):
        super().__init__(master)
        self.title("🔍 Revisión de Archivos Pesados (> 200 MB)")
        self.geometry("820x520")
        self.minsize(700, 420)
        self.configure(fg_color=COLOR_BG_DARK)

        self.items = sorted(items, key=lambda x: x.size, reverse=True)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Encabezado
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, padx=20, pady=(16, 8), sticky="ew")
        head.grid_columnconfigure(0, weight=1)

        t_lbl = ctk.CTkLabel(
            head,
            text=f"Archivos Pesados Detectados ({len(self.items)} archivos)",
            font=("Segoe UI", 16, "bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        t_lbl.grid(row=0, column=0, sticky="w")

        sub_lbl = ctk.CTkLabel(
            head,
            text="Revise qué archivos ocupan mayor espacio antes de decidir si eliminarlos o conservarlos.",
            font=("Segoe UI", 11),
            text_color=COLOR_TEXT_MUTED,
        )
        sub_lbl.grid(row=1, column=0, sticky="w")

        # Lista deslizable
        scroll_frame = ctk.CTkScrollableFrame(self, fg_color=COLOR_CARD_BG, corner_radius=10)
        scroll_frame.grid(row=1, column=0, padx=20, pady=8, sticky="nsew")
        scroll_frame.grid_columnconfigure(1, weight=1)

        for idx, itm in enumerate(self.items):
            row_f = ctk.CTkFrame(scroll_frame, fg_color="#181A22", corner_radius=8)
            row_f.grid(row=idx, column=0, padx=6, pady=4, sticky="ew")
            row_f.grid_columnconfigure(1, weight=1)

            # Peso
            sz_lbl = ctk.CTkLabel(
                row_f,
                text=format_bytes(itm.size),
                font=("Segoe UI", 12, "bold"),
                text_color=COLOR_WARNING,
                width=90,
                anchor="w",
            )
            sz_lbl.grid(row=0, column=0, padx=(12, 6), pady=8, sticky="w")

            # Nombre y ruta
            fn = os.path.basename(itm.path)
            info_f = ctk.CTkFrame(row_f, fg_color="transparent")
            info_f.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
            info_f.grid_columnconfigure(0, weight=1)

            fn_lbl = ctk.CTkLabel(info_f, text=fn, font=("Segoe UI", 12, "bold"), text_color=COLOR_TEXT_PRIMARY, anchor="w")
            fn_lbl.grid(row=0, column=0, sticky="w")

            fp_lbl = ctk.CTkLabel(info_f, text=itm.path, font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, anchor="w")
            fp_lbl.grid(row=1, column=0, sticky="w")

            # Botón para abrir en el Explorador
            btn_open = ctk.CTkButton(
                row_f,
                text="Abrir Ubicación",
                font=("Segoe UI", 10),
                width=110,
                height=26,
                fg_color="#2A2E39",
                hover_color="#373D4B",
                command=lambda p=itm.path: self._open_file_location(p),
            )
            btn_open.grid(row=0, column=2, padx=12, pady=8, sticky="e")

        # Barra inferior
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, padx=20, pady=(6, 16), sticky="ew")
        foot.grid_columnconfigure(0, weight=1)

        btn_copy = ctk.CTkButton(
            foot,
            text="📋 Copiar Lista de Rutas",
            font=("Segoe UI", 11),
            width=160,
            height=32,
            fg_color="#2A2E39",
            hover_color="#373D4B",
            command=self._copy_paths,
        )
        btn_copy.grid(row=0, column=0, sticky="w")

        btn_close = ctk.CTkButton(
            foot,
            text="Cerrar",
            font=("Segoe UI", 11, "bold"),
            width=100,
            height=32,
            fg_color=COLOR_ACCENT_BLUE,
            hover_color=COLOR_ACCENT_HOVER,
            command=self.destroy,
        )
        btn_close.grid(row=0, column=1, sticky="e")

    def _open_file_location(self, path: str):
        try:
            if os.path.exists(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:
            pass

    def _copy_paths(self):
        text = "\n".join([f"{format_bytes(it.size)}\t{it.path}" for it in self.items])
        self.clipboard_clear()
        self.clipboard_append(text)


# ==============================================================================
# COMPONENTES DE INTERFAZ GRÁFICA
# ==============================================================================
class StatCard(ctk.CTkFrame):
    """Tarjeta métrica superior moderna para mostrar métricas clave del sistema."""

    def __init__(
        self,
        master,
        title: str,
        initial_value: str,
        subtitle: str,
        accent_color: str = COLOR_ACCENT_BLUE,
        show_progress: bool = False,
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color=COLOR_CARD_BG,
            border_color=COLOR_CARD_BORDER,
            border_width=1,
            corner_radius=12,
            **kwargs,
        )

        self.grid_columnconfigure(0, weight=1)

        self.lbl_title = ctk.CTkLabel(
            self,
            text=title.upper(),
            font=FONT_CARD_LABEL,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.lbl_title.grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")

        self.lbl_value = ctk.CTkLabel(
            self,
            text=initial_value,
            font=FONT_CARD_VAL,
            text_color=accent_color,
            anchor="w",
        )
        self.lbl_value.grid(row=1, column=0, padx=16, pady=(0, 2), sticky="w")

        self.lbl_subtitle = ctk.CTkLabel(
            self,
            text=subtitle,
            font=FONT_CARD_SUB,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.lbl_subtitle.grid(row=2, column=0, padx=16, pady=(0, 8 if not show_progress else 4), sticky="w")

        self.progressbar = None
        if show_progress:
            self.progressbar = ctk.CTkProgressBar(
                self,
                height=8,
                corner_radius=4,
                fg_color="#2A2E39",
                progress_color=accent_color,
            )
            self.progressbar.set(0.0)
            self.progressbar.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")

    def update_data(
        self,
        value: str,
        subtitle: Optional[str] = None,
        progress: Optional[float] = None,
        title: Optional[str] = None,
    ):
        if title is not None:
            self.lbl_title.configure(text=title.upper())
        self.lbl_value.configure(text=value)
        if subtitle is not None:
            self.lbl_subtitle.configure(text=subtitle)
        if progress is not None and self.progressbar:
            self.progressbar.set(min(1.0, max(0.0, progress)))


class CategoryRow(ctk.CTkFrame):
    """Fila interactiva que representa una categoría seleccionable con badge y botón de detalle opcional."""

    def __init__(
        self,
        master,
        cat_id: str,
        icon: str,
        title: str,
        description: str,
        on_toggle_callback: Callable[[], None],
        on_review_callback: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color="#16181E",
            border_color="#242833",
            border_width=1,
            corner_radius=10,
            **kwargs,
        )
        self.cat_id = cat_id
        self.on_review_callback = on_review_callback
        self.grid_columnconfigure(1, weight=1)

        # Casilla de verificación
        self.var_checked = ctk.BooleanVar(value=True)
        self.checkbox = ctk.CTkCheckBox(
            self,
            text="",
            variable=self.var_checked,
            command=on_toggle_callback,
            width=24,
            checkbox_width=22,
            checkbox_height=22,
            corner_radius=6,
            fg_color=COLOR_ACCENT_BLUE,
            hover_color=COLOR_ACCENT_HOVER,
            border_color="#4B5563",
        )
        self.checkbox.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=10, sticky="w")

        # Título con icono
        self.lbl_title = ctk.CTkLabel(
            self,
            text=f"{icon}  {title}",
            font=("Segoe UI", 12, "bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        self.lbl_title.grid(row=0, column=1, padx=4, pady=(8, 0), sticky="w")

        # Descripción
        self.lbl_desc = ctk.CTkLabel(
            self,
            text=description,
            font=("Segoe UI", 10),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.lbl_desc.grid(row=1, column=1, padx=4, pady=(0, 8), sticky="w")

        # Botón de revisión detallada (para Archivos Pesados)
        self.btn_review = ctk.CTkButton(
            self,
            text="👁️ Revisar",
            font=("Segoe UI", 10),
            width=75,
            height=24,
            fg_color="#2A2E39",
            hover_color="#373D4B",
            command=lambda: self.on_review_callback(self.cat_id) if self.on_review_callback else None,
        )
        self.btn_review.grid(row=0, column=2, rowspan=2, padx=(4, 6), pady=10, sticky="e")
        self.btn_review.grid_remove()  # Oculto hasta que se detecten elementos

        # Badge indicador
        self.badge = ctk.CTkLabel(
            self,
            text="Sin analizar",
            font=("Segoe UI", 11, "bold"),
            text_color=COLOR_TEXT_MUTED,
            fg_color=COLOR_BADGE_BG,
            corner_radius=8,
            padx=10,
            pady=3,
        )
        self.badge.grid(row=0, column=3, rowspan=2, padx=12, pady=10, sticky="e")

    def is_selected(self) -> bool:
        return self.var_checked.get()

    def set_selected(self, val: bool):
        self.var_checked.set(val)

    def update_badge(
        self,
        text: str,
        highlight: bool = False,
        color: Optional[str] = None,
        show_review_btn: bool = False,
    ):
        self.badge.configure(
            text=text,
            text_color=color if color else (COLOR_SUCCESS if highlight else COLOR_TEXT_MUTED),
        )
        if show_review_btn and self.on_review_callback:
            self.btn_review.grid()
        else:
            self.btn_review.grid_remove()


# ==============================================================================
# APLICACIÓN PRINCIPAL (GUI)
# ==============================================================================
class DiskCleanerApp(ctk.CTk):
    """
    Ventana principal de la aplicación Limpiador y Optimizador de Disco con selector multi-unidad.
    """

    def __init__(self):
        super().__init__()

        # Configuración de ventana
        self.title("Limpiador y Optimizador de Disco | Pro Multi-Drive & USB")
        self.geometry("1060x820")
        self.minsize(900, 700)
        self.configure(fg_color=COLOR_BG_DARK)

        # Estados internos
        self.event_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.active_worker: Optional[threading.Thread] = None
        self.is_busy = False
        self.auto_clean_after_scan = False
        self.clean_large_files_confirmed = False

        self.latest_scan_results: Dict[str, CategoryScanResult] = {}
        self.category_rows: Dict[str, CategoryRow] = {}

        # Detección inicial de unidades
        self.mounted_drives: List[MountedDriveInfo] = WindowsSystemHelper.get_mounted_drives()
        self.selected_drive_mount = self.mounted_drives[0].mountpoint

        # Construcción de la interfaz
        self._build_ui()

        # Cargar datos iniciales
        self._update_disk_card(self.selected_drive_mount)
        self._update_ram_badge()

        # Iniciar despachador periódico de eventos (Event Pump)
        self.after(40, self._process_events)

    def _build_ui(self):
        """Construye todos los paneles y componentes visuales."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ----------------------------------------------------------------------
        # 1. ENCABEZADO Y BARRA DE CONTROL MULTI-DISCO / RAM
        # ----------------------------------------------------------------------
        top_container = ctk.CTkFrame(self, fg_color="transparent")
        top_container.grid(row=0, column=0, padx=24, pady=(16, 6), sticky="ew")
        top_container.grid_columnconfigure(0, weight=1)

        # Título y subtítulo
        title_box = ctk.CTkFrame(top_container, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        title_lbl = ctk.CTkLabel(
            title_box,
            text="🛠️ Limpiador y Optimizador de Disco",
            font=FONT_TITLE,
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        title_lbl.grid(row=0, column=0, sticky="w")

        subtitle_lbl = ctk.CTkLabel(
            title_box,
            text="Mantenimiento integral: discos internos, unidades externas, memorias USB y optimización de memoria RAM.",
            font=FONT_SUBTITLE,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        subtitle_lbl.grid(row=1, column=0, sticky="w", pady=(1, 0))

        # Toolbar: Selector Multi-Disco y Botón de RAM
        toolbar_f = ctk.CTkFrame(
            top_container,
            fg_color=COLOR_CARD_BG,
            border_color=COLOR_CARD_BORDER,
            border_width=1,
            corner_radius=10,
        )
        toolbar_f.grid(row=1, column=0, pady=(10, 0), sticky="ew")
        toolbar_f.grid_columnconfigure(2, weight=1)

        lbl_drive_icon = ctk.CTkLabel(
            toolbar_f,
            text="💾 Unidad a Optimizar:",
            font=("Segoe UI", 12, "bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        lbl_drive_icon.grid(row=0, column=0, padx=(14, 6), pady=8, sticky="w")

        drive_displays = [d.display for d in self.mounted_drives]
        self.opt_drives = ctk.CTkOptionMenu(
            toolbar_f,
            values=drive_displays,
            command=self._on_drive_menu_selected,
            font=("Segoe UI", 11, "bold"),
            fg_color="#2A2E39",
            button_color="#373D4B",
            button_hover_color="#4B5563",
            width=280,
            height=32,
            corner_radius=8,
        )
        self.opt_drives.set(drive_displays[0])
        self.opt_drives.grid(row=0, column=1, padx=(0, 6), pady=8, sticky="w")

        # Botón de recarga de unidades (🔄)
        self.btn_refresh_drives = ctk.CTkButton(
            toolbar_f,
            text="🔄",
            font=("Segoe UI", 13),
            width=36,
            height=32,
            corner_radius=8,
            fg_color="#2A2E39",
            hover_color="#373D4B",
            command=self._refresh_drives_list,
        )
        self.btn_refresh_drives.grid(row=0, column=2, padx=(0, 14), pady=8, sticky="w")

        # Indicador de RAM
        self.lbl_ram_status = ctk.CTkLabel(
            toolbar_f,
            text="RAM: Calculando...",
            font=("Segoe UI", 11),
            text_color=COLOR_TEXT_MUTED,
        )
        self.lbl_ram_status.grid(row=0, column=3, padx=(10, 8), pady=8, sticky="e")

        # Botón de Optimización de RAM
        self.btn_opt_ram = ctk.CTkButton(
            toolbar_f,
            text="⚡ Optimizar RAM",
            font=("Segoe UI", 11, "bold"),
            height=32,
            corner_radius=8,
            fg_color=COLOR_PURPLE,
            hover_color=COLOR_PURPLE_HOVER,
            command=self._optimize_ram_clicked,
        )
        self.btn_opt_ram.grid(row=0, column=4, padx=(0, 14), pady=8, sticky="e")

        # ----------------------------------------------------------------------
        # 2. PANEL SUPERIOR: TARJETAS DE ESTADÍSTICAS
        # ----------------------------------------------------------------------
        cards_container = ctk.CTkFrame(self, fg_color="transparent")
        cards_container.grid(row=1, column=0, padx=24, pady=(6, 10), sticky="ew")
        cards_container.grid_columnconfigure((0, 1, 2), weight=1, uniform="cards")

        self.card_recoverable = StatCard(
            cards_container,
            title="Espacio Recuperable",
            initial_value="0.00 B",
            subtitle="Listo para optimizar",
            accent_color=COLOR_ACCENT_BLUE,
        )
        self.card_recoverable.grid(row=0, column=0, padx=(0, 6), sticky="nsew")

        self.card_items = StatCard(
            cards_container,
            title="Elementos Detectados",
            initial_value="0 archivos",
            subtitle="En categorías activas",
            accent_color=COLOR_SUCCESS,
        )
        self.card_items.grid(row=0, column=1, padx=4, sticky="nsew")

        self.card_disk = StatCard(
            cards_container,
            title=f"Estado del Disco {self.selected_drive_mount[:2]}",
            initial_value="Calculando...",
            subtitle="Uso de la unidad",
            accent_color=COLOR_WARNING,
            show_progress=True,
        )
        self.card_disk.grid(row=0, column=2, padx=(6, 0), sticky="nsew")

        # ----------------------------------------------------------------------
        # 3. PANEL CENTRAL: SELECCIÓN DE CATEGORÍAS (SCROLLABLE) Y ACCIONES
        # ----------------------------------------------------------------------
        center_frame = ctk.CTkFrame(
            self,
            fg_color=COLOR_CARD_BG,
            border_color=COLOR_CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        center_frame.grid(row=2, column=0, padx=24, pady=4, sticky="ew")
        center_frame.grid_columnconfigure(0, weight=1)

        # Fila de control
        cat_header = ctk.CTkFrame(center_frame, fg_color="transparent")
        cat_header.grid(row=0, column=0, padx=16, pady=(10, 4), sticky="ew")
        cat_header.grid_columnconfigure(0, weight=1)

        sec_title = ctk.CTkLabel(
            cat_header,
            text="Áreas de Limpieza y Optimización Avanzada",
            font=("Segoe UI", 13, "bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        sec_title.grid(row=0, column=0, sticky="w")

        btn_select_all = ctk.CTkButton(
            cat_header,
            text="Seleccionar Todo",
            font=("Segoe UI", 11),
            width=105,
            height=26,
            fg_color="#2A2E39",
            hover_color="#373D4B",
            command=lambda: self._set_all_categories(True),
        )
        btn_select_all.grid(row=0, column=1, padx=(0, 6), sticky="e")

        btn_deselect_all = ctk.CTkButton(
            cat_header,
            text="Deseleccionar",
            font=("Segoe UI", 11),
            width=95,
            height=26,
            fg_color="#2A2E39",
            hover_color="#373D4B",
            command=lambda: self._set_all_categories(False),
        )
        btn_deselect_all.grid(row=0, column=2, sticky="e")

        # Contenedor deslizante para las 7 categorías
        cat_scroll_frame = ctk.CTkScrollableFrame(
            center_frame,
            fg_color="transparent",
            height=230,
            corner_radius=8,
        )
        cat_scroll_frame.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        cat_scroll_frame.grid_columnconfigure(0, weight=1)

        for idx, def_info in enumerate(CleaningCategoryRegistry.get_definitions()):
            row_widget = CategoryRow(
                cat_scroll_frame,
                cat_id=def_info["id"],
                icon=def_info["icon"],
                title=def_info["title"],
                description=def_info["desc"],
                on_toggle_callback=self._on_category_toggled,
                on_review_callback=self._open_category_review,
            )
            row_widget.grid(row=idx, column=0, pady=3, sticky="ew")
            self.category_rows[def_info["id"]] = row_widget

        # Barra de progreso y botones de acción
        action_container = ctk.CTkFrame(center_frame, fg_color="transparent")
        action_container.grid(row=2, column=0, padx=16, pady=(4, 12), sticky="ew")
        action_container.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(
            action_container,
            text="Listo. Seleccione la unidad, áreas deseadas y presione 'Analizar Unidad' o 'Limpiar Ahora'.",
            font=("Segoe UI", 11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.lbl_status.grid(row=0, column=0, columnspan=3, pady=(0, 4), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            action_container,
            height=10,
            corner_radius=5,
            fg_color="#232731",
            progress_color=COLOR_ACCENT_BLUE,
        )
        self.progress_bar.set(0.0)
        self.progress_bar.grid(row=1, column=0, columnspan=3, pady=(0, 10), sticky="ew")

        btn_frame = ctk.CTkFrame(action_container, fg_color="transparent")
        btn_frame.grid(row=2, column=0, columnspan=3, sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_analyze = ctk.CTkButton(
            btn_frame,
            text="🔍  Analizar Unidad",
            font=FONT_BUTTON,
            height=40,
            corner_radius=8,
            fg_color=COLOR_ACCENT_BLUE,
            hover_color=COLOR_ACCENT_HOVER,
            command=self._start_scan,
        )
        self.btn_analyze.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.btn_clean = ctk.CTkButton(
            btn_frame,
            text="🧹  Limpiar Ahora",
            font=FONT_BUTTON,
            height=40,
            corner_radius=8,
            fg_color=COLOR_SUCCESS,
            hover_color=COLOR_SUCCESS_HOVER,
            command=self._confirm_and_start_clean,
        )
        self.btn_clean.grid(row=0, column=1, padx=(8, 8), sticky="ew")

        self.btn_stop = ctk.CTkButton(
            btn_frame,
            text="⏹️  Detener",
            font=FONT_BUTTON,
            height=40,
            width=110,
            corner_radius=8,
            fg_color=COLOR_DANGER,
            hover_color=COLOR_DANGER_HOVER,
            state="disabled",
            command=self._stop_current_task,
        )
        self.btn_stop.grid(row=0, column=2, sticky="e")

        # ----------------------------------------------------------------------
        # 4. PANEL INFERIOR: LOG TERMINAL (#0F0F0F y TIPOGRAFÍA MONOSPACE)
        # ----------------------------------------------------------------------
        log_frame = ctk.CTkFrame(
            self,
            fg_color=COLOR_CARD_BG,
            border_color=COLOR_CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        log_frame.grid(row=3, column=0, padx=24, pady=(4, 16), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, padx=14, pady=(8, 4), sticky="ew")
        log_header.grid_columnconfigure(0, weight=1)

        lbl_log_title = ctk.CTkLabel(
            log_header,
            text="💻 Consola de Diagnóstico, Desinfección y Registro en Tiempo Real",
            font=("Segoe UI", 12, "bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        lbl_log_title.grid(row=0, column=0, sticky="w")

        btn_copy_log = ctk.CTkButton(
            log_header,
            text="Copiar Log",
            font=("Segoe UI", 10),
            width=75,
            height=24,
            fg_color="#2A2E39",
            hover_color="#373D4B",
            command=self._copy_log_to_clipboard,
        )
        btn_copy_log.grid(row=0, column=1, padx=(0, 6), sticky="e")

        btn_clear_log = ctk.CTkButton(
            log_header,
            text="Limpiar Log",
            font=("Segoe UI", 10),
            width=75,
            height=24,
            fg_color="#2A2E39",
            hover_color="#373D4B",
            command=self._clear_log,
        )
        btn_clear_log.grid(row=0, column=2, sticky="e")

        self.txt_log = ctk.CTkTextbox(
            log_frame,
            fg_color=COLOR_LOG_BG,
            text_color="#D1D5DB",
            font=FONT_LOG,
            corner_radius=8,
            wrap="char",
            activate_scrollbars=True,
        )
        self.txt_log.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="nsew")

        self.txt_log.tag_config("INFO", foreground="#60A5FA")
        self.txt_log.tag_config("SUCCESS", foreground="#34D399")
        self.txt_log.tag_config("WARN", foreground="#FBBF24")
        self.txt_log.tag_config("SKIP", foreground="#FBBF24")
        self.txt_log.tag_config("DELETE", foreground="#4ADE80")
        self.txt_log.tag_config("ERROR", foreground="#F87171")
        self.txt_log.tag_config("DANGER", foreground="#EF4444")
        self.txt_log.tag_config("PURPLE", foreground="#C084FC")
        self.txt_log.tag_config("DEBUG", foreground="#64748B")
        self.txt_log.tag_config("TIME", foreground="#4B5563")

        self._append_log_message(
            f"[SISTEMA] Motor multi-unidad iniciado. Unidad activa: {self.selected_drive_mount}",
            "INFO",
        )

    # --------------------------------------------------------------------------
    # GESTIÓN MULTI-DISCO Y MÉTRICAS DINÁMICAS
    # --------------------------------------------------------------------------
    def _refresh_drives_list(self):
        """Actualiza la lista de unidades montadas (útil al conectar o desconectar un USB)."""
        self.mounted_drives = WindowsSystemHelper.get_mounted_drives()
        new_displays = [d.display for d in self.mounted_drives]
        self.opt_drives.configure(values=new_displays)

        # Si la unidad anteriormente seleccionada aún existe, mantenerla
        current_in_list = False
        for d in self.mounted_drives:
            if d.mountpoint.upper() == self.selected_drive_mount.upper():
                self.opt_drives.set(d.display)
                current_in_list = True
                break

        if not current_in_list:
            self.selected_drive_mount = self.mounted_drives[0].mountpoint
            self.opt_drives.set(self.mounted_drives[0].display)

        self._update_disk_card(self.selected_drive_mount)
        self._append_log_message(
            f"[UNIDADES] Lista de unidades actualizada ({len(self.mounted_drives)} detectadas).",
            "INFO",
        )

    def _on_drive_menu_selected(self, selected_display: str):
        """Manejador cuando el usuario cambia de unidad en el desplegable."""
        for d in self.mounted_drives:
            if d.display == selected_display:
                self.selected_drive_mount = d.mountpoint
                break

        # Actualizar inmediatamente la tarjeta de estado del disco
        self._update_disk_card(self.selected_drive_mount)

        # Resetear datos de escaneo para la nueva unidad seleccionada
        self.latest_scan_results.clear()
        self.card_recoverable.update_data("0.00 B", subtitle="Listo para optimizar")
        self.card_items.update_data("0 archivos", subtitle="En categorías activas")

        for row in self.category_rows.values():
            row.update_badge("Sin analizar", highlight=False, show_review_btn=False)

        self.btn_analyze.configure(text=f"🔍  Analizar {self.selected_drive_mount[:2]}")
        self._append_log_message(
            f"[DISCO] Unidad seleccionada cambiada a: {selected_display}",
            "INFO",
        )

    def _update_disk_card(self, drive_mount: str):
        """Actualiza la tarjeta métrica de disco dinámicamente según la unidad activa."""
        stats = WindowsSystemHelper.get_disk_status(drive_mount)
        free_str = format_bytes(stats["free"])
        total_str = format_bytes(stats["total"])
        used_str = format_bytes(stats["used"])
        percent = stats["percent"]

        self.card_disk.update_data(
            title=f"Estado del Disco {drive_mount[:2]}",
            value=f"{free_str} Libres",
            subtitle=f"{used_str} / {total_str} ({percent}%)",
            progress=percent / 100.0,
        )

    def _update_ram_badge(self):
        """Actualiza el texto indicador del uso actual de memoria RAM."""
        try:
            vm = psutil.virtual_memory()
            used_str = format_bytes(vm.used)
            tot_str = format_bytes(vm.total)
            self.lbl_ram_status.configure(text=f"RAM: {vm.percent}% ({used_str} / {tot_str})")
        except Exception:
            pass

    def _optimize_ram_clicked(self):
        """Ejecuta la optimización de RAM en un hilo secundario sin congelar la app."""
        self.btn_opt_ram.configure(state="disabled", text="Optimizando...")
        self._append_log_message("[RAM] Iniciando vaciado de working sets y recolección de memoria...", "INFO")

        def _ram_thread():
            freed, trimmed, after_mem = WindowsSystemHelper.optimize_ram()
            self.event_queue.put(("RAM_OPTIMIZED", (freed, trimmed, after_mem)))

        threading.Thread(target=_ram_thread, daemon=True).start()

    # --------------------------------------------------------------------------
    # CONTROL DE CATEGORÍAS Y MODAL DE REVISIÓN
    # --------------------------------------------------------------------------
    def _set_all_categories(self, selected: bool):
        for row in self.category_rows.values():
            row.set_selected(selected)
        self._recalculate_selected_summary()

    def _on_category_toggled(self):
        self._recalculate_selected_summary()

    def _recalculate_selected_summary(self):
        total_bytes = 0
        total_items = 0
        for cat_id, row in self.category_rows.items():
            if row.is_selected() and cat_id in self.latest_scan_results:
                res = self.latest_scan_results[cat_id]
                total_bytes += res.total_bytes
                total_items += res.item_count

        self.card_recoverable.update_data(format_bytes(total_bytes))
        self.card_items.update_data(f"{total_items:,} archivos")

    def _open_category_review(self, cat_id: str):
        """Abre el diálogo modal de revisión para archivos pesados."""
        if cat_id in self.latest_scan_results:
            res = self.latest_scan_results[cat_id]
            if res.items:
                LargeFilesReviewDialog(self, res.items)

    def _get_active_categories(self) -> List[str]:
        return [cat_id for cat_id, row in self.category_rows.items() if row.is_selected()]

    # --------------------------------------------------------------------------
    # CONTROL DE TAREAS Y EJECUCIÓN MULTIHILO
    # --------------------------------------------------------------------------
    def _set_busy(self, busy: bool):
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        self.btn_analyze.configure(state=state)
        self.btn_clean.configure(state=state)
        self.opt_drives.configure(state=state)
        self.btn_refresh_drives.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def _start_scan(self):
        if self.is_busy:
            return

        active_cats = self._get_active_categories()
        if not active_cats:
            self._append_log_message("[AVISO] Seleccione al menos una categoría para analizar.", "WARN")
            self.lbl_status.configure(text="Seleccione al menos una categoría de la lista.")
            return

        self._set_busy(True)
        self.cancel_event.clear()
        self.progress_bar.configure(mode="indeterminate", progress_color=COLOR_ACCENT_BLUE)
        self.progress_bar.start()

        self.card_recoverable.update_data("Calculando...")
        self.card_items.update_data("Escaneando...")

        for cat_id in active_cats:
            self.category_rows[cat_id].update_badge("Analizando...", highlight=False, show_review_btn=False)

        self.active_worker = ScannerWorker(
            selected_categories=active_cats,
            selected_drive=self.selected_drive_mount,
            event_queue=self.event_queue,
            cancel_event=self.cancel_event,
        )
        self.active_worker.start()

    def _confirm_and_start_clean(self):
        if self.is_busy:
            return

        active_cats = self._get_active_categories()
        if not active_cats:
            self._append_log_message("[AVISO] Seleccione al menos una categoría para limpiar.", "WARN")
            self.lbl_status.configure(text="Seleccione al menos una categoría de la lista.")
            return

        needs_scan = not self.latest_scan_results or not any(c in self.latest_scan_results for c in active_cats)
        if needs_scan:
            self.auto_clean_after_scan = True
            self._append_log_message("[INFO] Realizando escaneo rápido previo antes de proceder a la limpieza...", "INFO")
            self._start_scan()
            return

        total_items = sum(self.latest_scan_results[c].item_count for c in active_cats if c in self.latest_scan_results)
        if total_items == 0:
            self._append_log_message("[INFO] No se detectaron elementos acumulados para limpiar en las áreas seleccionadas.", "INFO")
            self.lbl_status.configure(text="La unidad ya se encuentra optimizada.")
            return

        # Advertencia especial si se seleccionaron Archivos Pesados para evitar borrados accidentales
        clean_large_files = False
        if CleaningCategoryRegistry.CAT_LARGE_FILES in active_cats:
            large_res = self.latest_scan_results.get(CleaningCategoryRegistry.CAT_LARGE_FILES)
            if large_res and large_res.item_count > 0:
                self._append_log_message(
                    f"[SEGURIDAD] Se detectaron {large_res.item_count} archivos pesados ({format_bytes(large_res.total_bytes)}). "
                    f"Por seguridad se conservan para revisión del usuario a menos que se confirme su borrado individual.",
                    "WARN",
                )
                clean_large_files = False  # Por protección solo se listan para revisión

        self._start_clean_worker(active_cats, clean_large_files)

    def _start_clean_worker(self, active_cats: List[str], clean_large_files: bool):
        self._set_busy(True)
        self.cancel_event.clear()
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", progress_color=COLOR_SUCCESS)
        self.progress_bar.set(0.0)

        self.active_worker = CleanerWorker(
            scan_results=self.latest_scan_results,
            selected_categories=active_cats,
            clean_large_files=clean_large_files,
            event_queue=self.event_queue,
            cancel_event=self.cancel_event,
        )
        self.active_worker.start()

    def _stop_current_task(self):
        if self.is_busy:
            self.cancel_event.set()
            self.lbl_status.configure(text="Deteniendo tarea en curso de forma segura...")
            self.btn_stop.configure(state="disabled")

    # --------------------------------------------------------------------------
    # DESPACHADOR CENTRAL DE EVENTOS (THREAD-SAFE EVENT QUEUE)
    # --------------------------------------------------------------------------
    def _process_events(self):
        """Drena la cola de mensajes producida por los hilos secundarios."""
        try:
            while not self.event_queue.empty():
                item = self.event_queue.get_nowait()
                if not isinstance(item, tuple) or len(item) == 0:
                    continue

                event_type = item[0]
                payload = item[1] if len(item) > 1 else None

                if event_type == "LOG":
                    if isinstance(payload, tuple) and len(payload) >= 2:
                        msg, level = payload[0], payload[1]
                    else:
                        msg, level = payload, "INFO"
                    self._append_log_message(msg, level)

                elif event_type == "STATUS":
                    self.lbl_status.configure(text=str(payload))

                elif event_type == "PROGRESS":
                    curr, total = payload
                    if total > 0:
                        frac = curr / total
                        self.progress_bar.set(frac)
                        self.lbl_status.configure(text=f"Procesando elemento {curr} de {total} ({int(frac * 100)}%)...")

                elif event_type == "SCAN_TICK":
                    text, bytes_val, items_val = payload
                    self.lbl_status.configure(text=str(text))

                elif event_type == "SCAN_COMPLETE":
                    results, total_bytes, total_items, elapsed = payload
                    self.latest_scan_results = results
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                    self.progress_bar.set(1.0)
                    self._set_busy(False)

                    self.card_recoverable.update_data(
                        format_bytes(total_bytes),
                        subtitle="Espacio total a liberar",
                    )
                    self.card_items.update_data(
                        f"{total_items:,} archivos",
                        subtitle=f"Analizados en {elapsed:.1f}s",
                    )

                    # Actualizar badges de cada fila
                    for cat_id, cat_res in results.items():
                        if cat_id in self.category_rows:
                            show_rev = cat_id == CleaningCategoryRegistry.CAT_LARGE_FILES and cat_res.item_count > 0
                            if cat_res.item_count > 0:
                                badge_str = (
                                    f"{format_bytes(cat_res.total_bytes)}  ({cat_res.item_count:,} arch.)"
                                    if cat_res.total_bytes > 0
                                    else f"{cat_res.item_count:,} elementos"
                                )
                                self.category_rows[cat_id].update_badge(
                                    badge_str,
                                    highlight=True,
                                    show_review_btn=show_rev,
                                )
                            else:
                                self.category_rows[cat_id].update_badge("0 elementos (Limpio)", highlight=False)

                    self.lbl_status.configure(
                        text=f"Análisis finalizado en {self.selected_drive_mount}. Recuperable: {format_bytes(total_bytes)} en {total_items:,} elementos."
                    )

                    if self.auto_clean_after_scan:
                        self.auto_clean_after_scan = False
                        if total_items > 0:
                            active_cats = self._get_active_categories()
                            self._start_clean_worker(active_cats, clean_large_files=False)

                elif event_type == "SCAN_ABORTED":
                    self.auto_clean_after_scan = False
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                    self.progress_bar.set(0.0)
                    self._set_busy(False)
                    self.lbl_status.configure(text="Análisis cancelado por el usuario.")

                elif event_type == "CLEAN_COMPLETE":
                    summary = payload
                    self.progress_bar.set(1.0)
                    self._set_busy(False)

                    self._update_disk_card(self.selected_drive_mount)
                    self._update_ram_badge()

                    self.card_recoverable.update_data("0.00 B", subtitle="Unidad optimizada")
                    self.card_items.update_data("0 archivos", subtitle="Limpieza completada")

                    for cat_id in self._get_active_categories():
                        if cat_id in self.category_rows:
                            self.category_rows[cat_id].update_badge(
                                "Optimizado ✓",
                                highlight=True,
                                color=COLOR_SUCCESS,
                                show_review_btn=False,
                            )

                    self.latest_scan_results.clear()
                    self.lbl_status.configure(
                        text=f"¡Optimización finalizada! Se liberaron {format_bytes(summary['freed_bytes'])} ({summary['deleted_files']:,} archivos eliminados)."
                    )

                elif event_type == "CLEAN_ABORTED":
                    self.progress_bar.set(0.0)
                    self._set_busy(False)
                    self._update_disk_card(self.selected_drive_mount)
                    self.lbl_status.configure(text="Limpieza interrumpida por el usuario.")

                elif event_type == "RAM_OPTIMIZED":
                    freed, trimmed, after_mem = payload
                    self.btn_opt_ram.configure(state="normal", text="⚡ Optimizar RAM")
                    self._update_ram_badge()
                    self._append_log_message(
                        f"[RAM OPTIMIZADA] Se liberaron {format_bytes(freed)} de memoria RAM tras optimizar {trimmed} procesos. "
                        f"Uso actual de RAM: {after_mem.percent}% ({format_bytes(after_mem.used)} / {format_bytes(after_mem.total)}).",
                        "PURPLE",
                    )
                    self.lbl_status.configure(
                        text=f"Memoria RAM optimizada: {format_bytes(freed)} liberados con éxito."
                    )

        except queue.Empty:
            pass
        except Exception as e:
            print(f"Error procesando eventos de interfaz: {e}", file=sys.stderr)
        finally:
            self.after(35, self._process_events)

    # --------------------------------------------------------------------------
    # UTILIDADES DE CONSOLA DE LOGS (#0F0F0F)
    # --------------------------------------------------------------------------
    def _append_log_message(self, message: str, level: str = "INFO"):
        """Inserta un mensaje con timestamp y resaltado por etiquetas en la consola monospace."""
        timestamp = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "

        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", timestamp, "TIME")
        self.txt_log.insert("end", f"{message}\n", level)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")
        self._append_log_message("[SISTEMA] Registro de consola reiniciado.", "INFO")

    def _copy_log_to_clipboard(self):
        try:
            content = self.txt_log.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(content)
            self._append_log_message("[SISTEMA] Log copiado al portapapeles exitosamente.", "INFO")
        except Exception as e:
            self._append_log_message(f"[ERROR] No se pudo copiar el log: {e}", "ERROR")


# ==============================================================================
# PUNTO DE ENTRADA
# ==============================================================================
def main():
    try:
        app = DiskCleanerApp()
        app.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"Error fatal al iniciar la aplicación: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
