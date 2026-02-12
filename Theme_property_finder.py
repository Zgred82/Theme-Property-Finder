bl_info = {
    "name": "Theme Property Finder",
    "author": "Nanomanpro",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Edit > Preferences > Themes",
    "description": "Search and batch-sync theme properties across all Blender editors",
    "category": "User Interface",
}

import bpy

# --- UI MAPPING CONFIGURATION ---
UI_OVERRIDES = {
    "view_3d": {"name": "3D Viewport", "icon": 'VIEW3D'},
    "node_editor": {"name": "Node Editor", "icon": 'NODETREE'},
    "outliner": {"name": "Outliner", "icon": 'OUTLINER'},
    "properties": {"name": "Properties", "icon": 'PROPERTIES'},
    "image_editor": {"name": "Image/UV Editor", "icon": 'IMAGE_DATA'},
    "sequence_editor": {"name": "Video Sequencer", "icon": 'SEQUENCE'},
    "graph_editor": {"name": "Graph Editor/Drivers", "icon": 'GRAPH'},
    "dopesheet_editor": {"name": "Dope Sheet/Timeline", "icon": 'ACTION'},
    "text_editor": {"name": "Text Editor", "icon": 'TEXT'},
    "clip_editor": {"name": "Movie Clip Editor", "icon": 'TRACKER'},
    "nla_editor": {"name": "Nonlinear Animation", "icon": 'NLA'},
    "console": {"name": "Python Console", "icon": 'CONSOLE'},
    "info": {"name": "Info", "icon": 'INFO'},
    "statusbar": {"name": "Status Bar", "icon": 'STATUSBAR'},
    "topbar": {"name": "Top Bar", "icon": 'TOPBAR'},
    "file_browser": {"name": "File/Asset Browser", "icon": 'FILE_FOLDER'},
    "spreadsheet": {"name": "Spreadsheet", "icon": 'SPREADSHEET'},
    "common": {"name": "Common", "icon": 'SETTINGS'},
    "user_interface": {"name": "User Interface", "icon": 'WORKSPACE'},
}

class THEME_PROP_FINDER_ResultItem(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty()
    prop_id: bpy.props.StringProperty()
    label: bpy.props.StringProperty()
    group: bpy.props.StringProperty()
    icon: bpy.props.StringProperty()
    is_selected: bpy.props.BoolProperty(name="", default=False)

# --- OPERATORS ---

class THEME_PROP_FINDER_OT_SearchPopup(bpy.types.Operator):
    """Search for theme property names"""
    bl_idname = "wm.theme_prop_finder_search"
    bl_label = "Select Property"
    bl_property = "search_enum"

    def get_search_items(self, context):
        found_labels = set()
        theme = context.preferences.themes[0]
        def collect_labels(data_path):
            if not hasattr(data_path, "bl_rna"): return
            for p in data_path.bl_rna.properties:
                if p.type not in {'POINTER', 'COLLECTION'}:
                    if p.name and len(p.name) > 1: found_labels.add(p.name)
                elif p.type == 'POINTER':
                    try:
                        sub = getattr(data_path, p.identifier)
                        if sub and sub != data_path and "Theme" in sub.__class__.__name__:
                            collect_labels(sub)
                    except: pass
        for p_id in theme.bl_rna.properties.keys():
            if p_id.startswith("_") or p_id in {"rna_type", "bl_rna"}: continue
            try: collect_labels(getattr(theme, p_id))
            except: continue
        return [(n, n, "") for n in sorted(list(found_labels))]

    search_enum: bpy.props.EnumProperty(items=get_search_items)
    def execute(self, context):
        context.window_manager.theme_prop_finder_query = self.search_enum
        return {'FINISHED'}
    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'FINISHED'}

class THEME_PROP_FINDER_OT_ClearQuery(bpy.types.Operator):
    bl_idname = "wm.theme_prop_finder_clear"
    bl_label = "Reset"
    def execute(self, context):
        wm = context.window_manager
        wm.theme_prop_finder_query = ""
        wm.theme_prop_finder_results.clear()
        return {'FINISHED'}

class THEME_PROP_FINDER_OT_BatchSync(bpy.types.Operator):
    bl_idname = "wm.theme_prop_finder_sync"
    bl_label = "Sync"
    bl_options = {'UNDO'}
    source_path: bpy.props.StringProperty()

    def execute(self, context):
        prefs = context.preferences
        wm = context.window_manager
        updated_count = 0
        try:
            val = prefs.path_resolve(self.source_path)
            is_arr = hasattr(val, "__len__") and not isinstance(val, str)
            for res in wm.theme_prop_finder_results:
                if res.is_selected and res.path != self.source_path:
                    try:
                        target = prefs.path_resolve(res.path)
                        if is_arr:
                            channels = min(len(val), len(target))
                            if len(target) == 4: channels = 3
                            for i in range(channels): target[i] = val[i]
                            updated_count += 1
                        else:
                            parts = res.path.rsplit(".", 1)
                            setattr(prefs.path_resolve(parts[0]), parts[1], val)
                            updated_count += 1
                    except: continue
            if updated_count > 0: 
                self.report({'INFO'}, f"Theme Property Finder: Updated {updated_count} items")
            return {'FINISHED'}
        except: return {'CANCELLED'}

class THEME_PROP_FINDER_OT_SelectMatching(bpy.types.Operator):
    bl_idname = "wm.theme_prop_finder_select"
    bl_label = "Select Matching"
    def execute(self, context):
        wm = context.window_manager
        q = wm.theme_prop_finder_query.lower().strip()
        if not q: return {'CANCELLED'}
        for res in wm.theme_prop_finder_results: res.is_selected = (res.label.lower() == q)
        return {'FINISHED'}

class THEME_PROP_FINDER_OT_DeselectAll(bpy.types.Operator):
    bl_idname = "wm.theme_prop_finder_deselect"
    bl_label = "Deselect All"
    def execute(self, context):
        for res in context.window_manager.theme_prop_finder_results: res.is_selected = False
        return {'FINISHED'}

# --- CORE LOGIC ---

def perform_theme_search(self, context):
    wm = context.window_manager
    wm.theme_prop_finder_results.clear()
    query = wm.theme_prop_finder_query.lower().strip()
    if not query: return
    theme = context.preferences.themes[0]
    
    def scan(data_path, api_path, breadcrumb, icon):
        if not hasattr(data_path, "bl_rna"): return
        for p_id, p_data in data_path.bl_rna.properties.items():
            if p_id in {"rna_type", "bl_rna"}: continue
            full_api = f"{api_path}.{p_id}"
            if p_data.type not in {'POINTER', 'COLLECTION'}:
                if query in p_data.name.lower() or query in p_id.lower():
                    res = wm.theme_prop_finder_results.add()
                    res.path, res.prop_id, res.label, res.group, res.icon = f"themes[0].{full_api}", p_id, p_data.name, breadcrumb, icon
            elif p_data.type == 'POINTER':
                try:
                    sub = getattr(data_path, p_id)
                    if sub and sub != data_path:
                        sub_label = p_data.name if p_data.name else p_id.replace("_", " ").title()
                        scan(sub, full_api, f"{breadcrumb} > {sub_label}", icon)
                except: pass

    for p_id in theme.bl_rna.properties.keys():
        if p_id in {"rna_type", "bl_rna", "bone_color_sets", "collection_colors"}: continue
        try:
            attr = getattr(theme, p_id)
            if attr:
                info = UI_OVERRIDES.get(p_id, {"name": p_id.replace("_", " ").title(), "icon": 'PREFERENCES'})
                scan(attr, p_id, info["name"], info["icon"])
        except: continue

# --- UI DRAW ---

def draw_theme_prop_finder_ui(self, context):
    layout = self.layout
    wm = context.window_manager
    
    main_box = layout.box()
    row = main_box.row(align=True)
    row.operator("wm.theme_prop_finder_search", text="List", icon='MENU_PANEL')
    row.prop(wm, "theme_prop_finder_query", text="", icon='VIEWZOOM', placeholder="Search theme properties...")
    if wm.theme_prop_finder_query:
        row.operator("wm.theme_prop_finder_clear", text="", icon='X')

    if not wm.theme_prop_finder_results: return
    
    ctrl = main_box.row(align=True)
    ctrl.operator("wm.theme_prop_finder_select", text="Select Matching", icon='CHECKBOX_HLT')
    if sum(1 for r in wm.theme_prop_finder_results if r.is_selected) > 0:
        ctrl.operator("wm.theme_prop_finder_deselect", text="Deselect", icon='X')

    current_group = ""
    group_col = None
    for res in wm.theme_prop_finder_results:
        if res.group != current_group:
            current_group = res.group
            g_box = main_box.box()
            g_box.label(text=res.group, icon=res.icon)
            group_col = g_box.column(align=True)
        
        try:
            owner = context.preferences.path_resolve(res.path.rsplit(".", 1)[0])
            indent_row = group_col.split(factor=0.03, align=True)
            indent_row.label(text="") 
            r = indent_row.row(align=True)
            r.prop(res, "is_selected", text="")
            split = r.split(factor=0.40)
            split.label(text=f"• {res.label}")
            prow = split.row(align=True)
            prow.prop(owner, res.prop_id, text="")
            if res.is_selected:
                prow.operator("wm.theme_prop_finder_sync", text="", icon='PASTEDOWN').source_path = res.path
            else:
                prow.label(text="", icon='BLANK1')
        except: continue

# --- REGISTRATION ---

classes = (
    THEME_PROP_FINDER_ResultItem, 
    THEME_PROP_FINDER_OT_SearchPopup, 
    THEME_PROP_FINDER_OT_ClearQuery, 
    THEME_PROP_FINDER_OT_BatchSync, 
    THEME_PROP_FINDER_OT_SelectMatching, 
    THEME_PROP_FINDER_OT_DeselectAll
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.WindowManager.theme_prop_finder_query = bpy.props.StringProperty(update=perform_theme_search)
    bpy.types.WindowManager.theme_prop_finder_results = bpy.props.CollectionProperty(type=THEME_PROP_FINDER_ResultItem)
    
    bpy.types.USERPREF_PT_theme.prepend(draw_theme_prop_finder_ui)

def unregister():
    bpy.types.USERPREF_PT_theme.remove(draw_theme_prop_finder_ui)
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        
    del bpy.types.WindowManager.theme_prop_finder_query
    del bpy.types.WindowManager.theme_prop_finder_results

if __name__ == "__main__":
    register()