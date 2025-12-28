// Adobe After Effects ExtendScript/UXP Type Definitions

declare global {
  const app: Application;

  interface Application {
    project: Project;
    activeViewer: Viewer | null;
    version: string;
    buildNumber: string;
    isRenderEngine: boolean;
    exitCode: number;
    memoryInUse: number;
    exitAfterLaunchAndEval: boolean;
    saveProjectOnCrash: boolean;
    beginUndoGroup(name: string): void;
    endUndoGroup(): void;
    quit(): void;
    executeCommand(commandId: number): void;
  }

  interface Project {
    file: File | null;
    rootFolder: FolderItem;
    items: ItemCollection;
    activeItem: Item | null;
    selection: Item[];
    numItems: number;
    renderQueue: RenderQueue;
    bitsPerChannel: number;
    transparencyGridThumbnails: boolean;
    gpuAccelType: GpuAccelType;
    close(save: CloseOptions): boolean;
    save(file?: File): void;
    saveWithDialog(): boolean;
    importFile(importOptions: ImportOptions): Item;
    importPlaceholder(name: string, width: number, height: number, frameRate: number, duration: number): PlaceholderItem;
    importFileWithDialog(): Item[] | null;
    showWindow(doShow: boolean): void;
    autoFixExpressions(oldText: string, newText: string): void;
    item(index: number): Item;
    consolidateFootage(): number;
    removeUnusedFootage(): number;
    reduceProject(arrayOfItems: Item[]): number;
  }

  interface ItemCollection {
    length: number;
    [index: number]: Item;
  }

  interface Item {
    name: string;
    comment: string;
    id: number;
    parentFolder: FolderItem;
    selected: boolean;
    typeName: string;
    label: number;
    remove(): void;
  }

  interface AVItem extends Item {
    width: number;
    height: number;
    pixelAspect: number;
    frameRate: number;
    frameDuration: number;
    duration: number;
    useProxy: boolean;
    proxySource: FootageSource | null;
    time: number;
    usedIn: CompItem[];
    hasVideo: boolean;
    hasAudio: boolean;
    footageMissing: boolean;
  }

  interface CompItem extends AVItem {
    layers: LayerCollection;
    selectedLayers: Layer[];
    selectedProperties: Property[];
    numLayers: number;
    hideShyLayers: boolean;
    motionBlur: boolean;
    draft3d: boolean;
    frameBlending: boolean;
    preserveNestedFrameRate: boolean;
    preserveNestedResolution: boolean;
    bgColor: [number, number, number];
    displayStartTime: number;
    displayStartFrame: number;
    shutterAngle: number;
    shutterPhase: number;
    motionBlurSamplesPerFrame: number;
    motionBlurAdaptiveSampleLimit: number;
    workAreaStart: number;
    workAreaDuration: number;
    resolutionFactor: [number, number];
    renderer: string;
    renderers: string[];
    duplicate(): CompItem;
    layer(index: number | string): Layer;
    openInViewer(): Viewer | null;
    saveFrameToPng(time: number, file: File): void;
    ramPreviewTest(unknown: any, zoom: number, fromCurrentTime: boolean): void;
  }

  interface FolderItem extends Item {
    items: ItemCollection;
    numItems: number;
    item(index: number): Item;
  }

  interface FootageItem extends AVItem {
    file: File | null;
    mainSource: FootageSource;
    replace(file: File): void;
    replaceWithPlaceholder(name: string, width: number, height: number, frameRate: number, duration: number): void;
    replaceWithSequence(file: File, forceAlphabetical: boolean): void;
    replaceWithSolid(color: [number, number, number], name: string, width: number, height: number, pixelAspect: number): void;
    openInViewer(): Viewer | null;
  }

  interface PlaceholderItem extends FootageItem {}

  interface SolidSource {
    color: [number, number, number];
  }

  interface FootageSource {
    file: File | null;
    isStill: boolean;
    fieldSeparationType: FieldSeparationType;
    highQualityFieldSeparation: boolean;
    removePulldown: PulldownPhase;
    loop: number;
    nativeFrameRate: number;
    displayFrameRate: number;
    conformFrameRate: number;
    alphaMode: AlphaMode;
    premulColor: [number, number, number];
    invertAlpha: boolean;
    hasAlpha: boolean;
    guessAlphaMode(): void;
    guessPulldown(method: PulldownMethod): void;
  }

  interface LayerCollection {
    length: number;
    [index: number]: Layer;
    add(item: AVItem, duration?: number): AVLayer;
    addNull(duration?: number): AVLayer;
    addSolid(color: [number, number, number], name: string, width: number, height: number, pixelAspect: number, duration?: number): AVLayer;
    addText(text?: string): TextLayer;
    addShape(): ShapeLayer;
    addCamera(name: string, centerPoint: [number, number]): CameraLayer;
    addLight(name: string, centerPoint: [number, number]): LightLayer;
    precompose(indexes: number[], name: string, moveAllAttributes?: boolean): CompItem;
    byName(name: string): Layer | null;
  }

  interface Layer {
    index: number;
    name: string;
    parent: Layer | null;
    time: number;
    startTime: number;
    stretch: number;
    inPoint: number;
    outPoint: number;
    enabled: boolean;
    solo: boolean;
    shy: boolean;
    locked: boolean;
    hasVideo: boolean;
    active: boolean;
    nullLayer: boolean;
    selectedProperties: Property[];
    comment: string;
    containingComp: CompItem;
    isNameSet: boolean;
    label: number;
    source: AVItem | null;
    remove(): void;
    duplicate(): Layer;
    copyToComp(comp: CompItem): void;
    moveToBeginning(): void;
    moveToEnd(): void;
    moveAfter(layer: Layer): void;
    moveBefore(layer: Layer): void;
    setParentWithJump(newParent: Layer | null): void;
    property(propertyName: string | number): Property | PropertyGroup | null;
  }

  interface AVLayer extends Layer {
    source: AVItem;
    isNameFromSource: boolean;
    height: number;
    width: number;
    audioEnabled: boolean;
    motionBlur: boolean;
    effectsActive: boolean;
    adjustmentLayer: boolean;
    guideLayer: boolean;
    threeDLayer: boolean;
    threeDPerChar: boolean;
    collapseTransformation: boolean;
    frameBlending: boolean;
    frameBlendingType: FrameBlendingType;
    canSetCollapseTransformation: boolean;
    canSetTimeRemapEnabled: boolean;
    timeRemapEnabled: boolean;
    hasAudio: boolean;
    audioActive: boolean;
    blendingMode: BlendingMode;
    preserveTransparency: boolean;
    trackMatteType: TrackMatteType;
    isTrackMatte: boolean;
    hasTrackMatte: boolean;
    quality: LayerQuality;
    samplingQuality: LayerSamplingQuality;
    autoOrient: AutoOrientType;
    sourceRectAtTime(time: number, includeExtents: boolean): { top: number; left: number; width: number; height: number };
    openInViewer(): Viewer | null;
    calculateTransformFromPoints(pointTopLeft: [number, number, number], pointTopRight: [number, number, number], pointBottomRight: [number, number, number]): object;
    replaceSource(newSource: AVItem, fixExpressions: boolean): void;
    sourcePointToComp(point: [number, number, number]): [number, number, number];
    compPointToSource(point: [number, number, number]): [number, number, number];
  }

  interface TextLayer extends AVLayer {}
  interface ShapeLayer extends AVLayer {}
  interface CameraLayer extends Layer {}
  interface LightLayer extends Layer {}

  interface Property {
    name: string;
    matchName: string;
    propertyIndex: number;
    propertyDepth: number;
    propertyType: PropertyType;
    parentProperty: PropertyGroup | null;
    isModified: boolean;
    canSetEnabled: boolean;
    enabled: boolean;
    active: boolean;
    elided: boolean;
    isEffect: boolean;
    isMask: boolean;
    selected: boolean;
    numKeys: number;
    propertyValueType: PropertyValueType;
    value: any;
    hasMin: boolean;
    hasMax: boolean;
    minValue: number;
    maxValue: number;
    isSpatial: boolean;
    canVaryOverTime: boolean;
    isTimeVarying: boolean;
    numKeys: number;
    unitsText: string;
    expression: string;
    expressionEnabled: boolean;
    expressionError: string;
    selectedKeys: number[];
    propertyGroup(countUp: number): PropertyGroup | null;
    remove(): void;
    duplicate(): Property;
    keyValue(keyIndex: number): any;
    keyTime(keyIndex: number): number;
    nearestKeyIndex(time: number): number;
    addKey(time: number): number;
    removeKey(keyIndex: number): void;
    setValueAtTime(time: number, value: any): void;
    setValueAtKey(keyIndex: number, value: any): void;
    setValue(value: any): void;
    valueAtTime(time: number, preExpression?: boolean): any;
  }

  interface PropertyGroup extends Property {
    numProperties: number;
    property(index: number | string): Property | PropertyGroup | null;
    addProperty(name: string): Property | PropertyGroup;
    canAddProperty(name: string): boolean;
  }

  interface RenderQueue {
    items: RenderQueueItemCollection;
    numItems: number;
    rendering: boolean;
    item(index: number): RenderQueueItem;
    showWindow(show: boolean): void;
    render(): void;
    pauseRendering(pause: boolean): void;
    stopRendering(): void;
  }

  interface RenderQueueItemCollection {
    length: number;
    [index: number]: RenderQueueItem;
    add(comp: CompItem): RenderQueueItem;
  }

  interface RenderQueueItem {
    comp: CompItem;
    status: RQItemStatus;
    startTime: Date | null;
    elapsedSeconds: number | null;
    logType: LogType;
    render: boolean;
    skipFrames: number;
    numOutputModules: number;
    onStatusChanged: (() => void) | null;
    outputModules: OutputModuleCollection;
    templates: string[];
    timeSpanStart: number;
    timeSpanDuration: number;
    outputModule(index: number): OutputModule;
    remove(): void;
    saveAsTemplate(name: string): void;
    duplicate(): RenderQueueItem;
    applyTemplate(name: string): void;
  }

  interface OutputModuleCollection {
    length: number;
    [index: number]: OutputModule;
    add(): OutputModule;
  }

  interface OutputModule {
    name: string;
    templates: string[];
    file: File | null;
    postRenderAction: PostRenderAction;
    includeSourceXMP: boolean;
    remove(): void;
    saveAsTemplate(name: string): void;
    applyTemplate(name: string): void;
  }

  interface Viewer {
    type: ViewerType;
    active: boolean;
    activeViewIndex: number;
    views: View[];
    maximized: boolean;
    setActive(): boolean;
  }

  interface View {
    active: boolean;
    options: ViewOptions;
  }

  interface ViewOptions {
    channels: ChannelType;
    checkerboards: boolean;
    exposure: number;
    fastPreview: FastPreviewType;
    zoom: number;
  }

  interface ImportOptions {
    file: File;
    forceAlphabetical?: boolean;
    importAs?: ImportAsType;
    sequence?: boolean;
  }

  interface File {
    name: string;
    path: string;
    fullName: string;
    displayName: string;
    exists: boolean;
    parent: Folder;
    readonly: boolean;
    length: number;
    created: Date;
    modified: Date;
    fsName: string;
    absoluteURI: string;
    relativeURI: string;
    open(mode?: string, type?: string, creator?: string): boolean;
    close(): boolean;
    read(chars?: number): string;
    readch(): string;
    readln(): string;
    write(...args: any[]): boolean;
    writeln(...args: any[]): boolean;
    seek(pos: number, mode?: number): boolean;
    tell(): number;
    copy(target: string | File): boolean;
    remove(): boolean;
    rename(newName: string): boolean;
    resolve(): File | null;
    execute(): boolean;
    openDlg(prompt?: string, filter?: string, multiSelect?: boolean): File | File[] | null;
    saveDlg(prompt?: string, filter?: string): File | null;
  }

  interface Folder {
    name: string;
    path: string;
    fullName: string;
    displayName: string;
    exists: boolean;
    parent: Folder | null;
    fsName: string;
    absoluteURI: string;
    relativeURI: string;
    create(): boolean;
    remove(): boolean;
    rename(newName: string): boolean;
    resolve(): Folder | null;
    execute(): boolean;
    getFiles(mask?: string | ((file: File | Folder) => boolean)): (File | Folder)[];
    selectDlg(prompt?: string): Folder | null;
  }

  // Enums
  enum CloseOptions {
    DO_NOT_SAVE_CHANGES = 1,
    PROMPT_TO_SAVE_CHANGES = 2,
    SAVE_CHANGES = 3
  }

  enum ImportAsType {
    COMP = 1,
    FOOTAGE = 2,
    COMP_CROPPED_LAYERS = 3,
    PROJECT = 4
  }

  enum GpuAccelType {
    CUDA = 1,
    METAL = 2,
    OPENCL = 3,
    SOFTWARE = 4
  }

  enum FieldSeparationType {
    OFF = 1,
    UPPER_FIELD_FIRST = 2,
    LOWER_FIELD_FIRST = 3
  }

  enum PulldownPhase {
    OFF = 1,
    SSWWW = 2,
    SWWWS = 3,
    SWWWW_24P_ADVANCE = 4,
    WSSWW = 5,
    WSWWW_24P_ADVANCE = 6,
    WWSSW = 7,
    WWSWW_24P_ADVANCE = 8,
    WWWSS = 9,
    WWWSW_24P_ADVANCE = 10,
    WWWWS_24P_ADVANCE = 11
  }

  enum PulldownMethod {
    PULLDOWN_3_2 = 1,
    ADVANCE_24P = 2
  }

  enum AlphaMode {
    IGNORE = 1,
    STRAIGHT = 2,
    PREMULTIPLIED = 3
  }

  enum FrameBlendingType {
    NO_FRAME_BLEND = 1,
    FRAME_MIX = 2,
    PIXEL_MOTION = 3
  }

  enum BlendingMode {
    ADD = 1,
    ALPHA_ADD = 2,
    CLASSIC_COLOR_BURN = 3,
    CLASSIC_COLOR_DODGE = 4,
    CLASSIC_DIFFERENCE = 5,
    COLOR = 6,
    COLOR_BURN = 7,
    COLOR_DODGE = 8,
    DANCING_DISSOLVE = 9,
    DARKEN = 10,
    DARKER_COLOR = 11,
    DIFFERENCE = 12,
    DISSOLVE = 13,
    EXCLUSION = 14,
    HARD_LIGHT = 15,
    HARD_MIX = 16,
    HUE = 17,
    LIGHTEN = 18,
    LIGHTER_COLOR = 19,
    LINEAR_BURN = 20,
    LINEAR_DODGE = 21,
    LINEAR_LIGHT = 22,
    LUMINESCENT_PREMUL = 23,
    LUMINOSITY = 24,
    MULTIPLY = 25,
    NORMAL = 26,
    OVERLAY = 27,
    PIN_LIGHT = 28,
    SATURATION = 29,
    SCREEN = 30,
    SILHOUETE_ALPHA = 31,
    SILHOUETTE_LUMA = 32,
    SOFT_LIGHT = 33,
    STENCIL_ALPHA = 34,
    STENCIL_LUMA = 35,
    VIVID_LIGHT = 36,
    SUBTRACT = 37
  }

  enum TrackMatteType {
    ALPHA = 1,
    ALPHA_INVERTED = 2,
    LUMA = 3,
    LUMA_INVERTED = 4,
    NO_TRACK_MATTE = 5
  }

  enum LayerQuality {
    BEST = 1,
    DRAFT = 2,
    WIREFRAME = 3
  }

  enum LayerSamplingQuality {
    BICUBIC = 1,
    BILINEAR = 2
  }

  enum AutoOrientType {
    ALONG_PATH = 1,
    CAMERA_OR_POINT_OF_INTEREST = 2,
    CHARACTERS_TOWARD_CAMERA = 3,
    NO_AUTO_ORIENT = 4
  }

  enum PropertyType {
    PROPERTY = 1,
    INDEXED_GROUP = 2,
    NAMED_GROUP = 3
  }

  enum PropertyValueType {
    NO_VALUE = 1,
    ThreeD_SPATIAL = 2,
    ThreeD = 3,
    TwoD_SPATIAL = 4,
    TwoD = 5,
    OneD = 6,
    COLOR = 7,
    CUSTOM_VALUE = 8,
    MARKER = 9,
    LAYER_INDEX = 10,
    MASK_INDEX = 11,
    SHAPE = 12,
    TEXT_DOCUMENT = 13
  }

  enum RQItemStatus {
    WILL_CONTINUE = 1,
    NEEDS_OUTPUT = 2,
    UNQUEUED = 3,
    QUEUED = 4,
    RENDERING = 5,
    USER_STOPPED = 6,
    ERR_STOPPED = 7,
    DONE = 8
  }

  enum LogType {
    ERRORS_ONLY = 1,
    ERRORS_AND_SETTINGS = 2,
    ERRORS_AND_PER_FRAME_INFO = 3
  }

  enum PostRenderAction {
    NONE = 1,
    IMPORT = 2,
    IMPORT_AND_REPLACE_USAGE = 3,
    SET_PROXY = 4
  }

  enum ViewerType {
    VIEWER_COMPOSITION = 1,
    VIEWER_LAYER = 2,
    VIEWER_FOOTAGE = 3,
    VIEWER_FLOWCHART = 4
  }

  enum ChannelType {
    CHANNEL_RGB = 1,
    CHANNEL_RED = 2,
    CHANNEL_GREEN = 3,
    CHANNEL_BLUE = 4,
    CHANNEL_ALPHA = 5,
    CHANNEL_RGB_STRAIGHT = 6,
    CHANNEL_ALPHA_BOUNDARY = 7,
    CHANNEL_ALPHA_OVERLAY = 8
  }

  enum FastPreviewType {
    FP_OFF = 1,
    FP_ADAPTIVE_RESOLUTION = 2,
    FP_DRAFT = 3,
    FP_FAST_DRAFT = 4,
    FP_WIREFRAME = 5
  }
}

export {};
