# 🛠️ Limpiador y Optimizador de Disco (Pro Multi-Drive & USB Edition)

Una aplicación de escritorio nativa para Windows desarrollada con **Python**, **CustomTkinter** y **Psutil**, diseñada bajo los más altos estándares de ingeniería de software para proporcionar una limpieza profunda, segura, modular y visualmente moderna del almacenamiento local, discos externos, memorias USB y memoria RAM.

---

## 🚀 Nuevas Funcionalidades y Capacidades

### 1. 💾 Selector Multi-Disco (Panel Superior):
- **Detección Automática de Unidades:** Identifica en tiempo real todas las unidades montadas en el sistema (`psutil.disk_partitions()`) con su letra de volumen, etiqueta y tipo de formato (ej. `C:\ (Sistema - NTFS)`, `E:\ (ADATA External - NTFS)`, `F:\ (USB Kingston - FAT32)`).
- **Botón de Recarga Rápida (🔄):** Actualiza instantáneamente el desplegable al conectar o desconectar memorias USB o discos duros externos.
- **Métricas Dinámicas en Tiempo Real:** Al cambiar de unidad en el desplegable, la tarjeta **Estado del Disco** actualiza al instante el espacio libre, usado, total y la barra porcentual correspondiente a la unidad seleccionada.

### 2. ⚡ Optimización de Memoria RAM:
- Botón dedicado en el panel superior (`⚡ Optimizar RAM`).
- Ejecuta vaciado de Working Sets de procesos del sistema vía Win32 API (`psapi.EmptyWorkingSet`) y recolección de basura (`gc.collect()`), reportando la cantidad exacta de memoria RAM liberada en tiempo real.

### 3. 🛡️ Nuevas Casillas de Limpieza Especializadas:
- 🔍 **Archivos Pesados (> 200 MB):** Detecta archivos que superen los 200 MB en la unidad seleccionada. Incluye un botón interactivo `👁️ Revisar` que abre una ventana modal para inspeccionar los archivos, su peso, ruta y abrir directamente su ubicación en el Explorador de Windows.
- 📁 **Carpetas Vacías:** Identifica y elimina de forma recursiva directorios huérfanos sin contenido para mantener una estructura de archivos limpia.
- 🛡️ **Desinfección USB / Accesos Directos:** 
  - Elimina scripts maliciosos y de autoejecución (`autorun.inf`, `.vbs`, `.bat`, `.cmd`).
  - Detecta y elimina accesos directos maliciosos (`.lnk`) característicos de virus de USB y accesos dañados.
  - **Recuperación de Archivos:** Desoculta y restaura automáticamente carpetas originales que hayan sido ocultadas por malware mediante atributos de sistema (`attrib -h -s`).

### 4. 🧰 Áreas Clásicas de Optimización:
- ⚡ **Archivos temporales del sistema (`%TEMP%`, `C:\Windows\Temp`)**
- 🌐 **Caché de navegadores web (Chrome, Edge, Firefox, Brave, Opera)**
- 📥 **Descargas incompletas (`.crdownload`, `.part`, `.tmp`, `.partial`) con protección de descargas activas**
- 🗑️ **Papelera de reciclaje nativa de Windows (Win32 Shell API) y reportes de error (CrashDumps, WER)**

---

## 📦 Estructura del Proyecto

```text
disk_cleaner/
│
├── main.py              # Código fuente modular con arquitectura multihilo
├── requirements.txt     # Dependencias: customtkinter, psutil, Pillow
└── README.md            # Documentación completa y guía de uso
```

---

## ⚙️ Instalación y Requisitos

### Requisitos:
- **Python 3.10 o superior** en Windows 10 u 11.
- Dependencias indicadas en `requirements.txt`.

### Instalación:
```bash
pip install -r requirements.txt
```

---

## ▶️ Ejecución

```bash
python main.py
```
