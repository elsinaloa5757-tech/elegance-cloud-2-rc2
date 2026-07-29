import 'dart:convert';
import 'dart:html' as html;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';

const Color bg = Color(0xFF02080C);
const Color panel = Color(0xD9101B24);
const Color panel2 = Color(0xE8152632);
const Color ice = Color(0xFF65D9FF);
const Color ice2 = Color(0xFF1EA8E8);
const Color muted = Color(0xFF91A7B4);
const Color line = Color(0x5536BFEF);
const Map<String, List<String>> universalCategories = {
  'Calzado': ['Sneakers', 'Botas', 'Botines', 'Zapatos', 'Sandalias', 'Tacones', 'Mocasines'],
  'Ropa': ['Playeras', 'Camisas', 'Sudaderas', 'Chamarras', 'Pantalones', 'Jeans', 'Shorts', 'Vestidos', 'Faldas'],
  'Bolsas': ['Bolsos', 'Mochilas', 'Crossbody', 'Tote', 'Clutch', 'Carteras'],
  'Accesorios': ['Gorras', 'Cinturones', 'Lentes', 'Bufandas', 'Guantes', 'Llaveros'],
  'Joyería': ['Relojes', 'Pulseras', 'Collares', 'Anillos', 'Aretes'],
  'Equipaje': ['Maletas', 'Carry-on', 'Duffles', 'Organizadores'],
  'Otros': ['Coleccionables', 'Cuidado del producto', 'Empaque'],
};

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const EleganceApp());
}

class EleganceApp extends StatefulWidget {
  const EleganceApp({super.key});

  @override
  State<EleganceApp> createState() => _EleganceAppState();
}

class _EleganceAppState extends State<EleganceApp> {
  final AppStore store = AppStore();
  bool ready = false;

  @override
  void initState() {
    super.initState();
    store.load();
    Future.microtask(store.syncFromBackend);
    ready = true;
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'elegance',
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: bg,
        colorScheme: const ColorScheme.dark(primary: ice, secondary: ice2),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xAA0A151D),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: const BorderSide(color: line),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: const BorderSide(color: line),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: const BorderSide(color: ice),
          ),
          labelStyle: const TextStyle(color: muted),
        ),
        dialogTheme: DialogThemeData(
          backgroundColor: const Color(0xFF071119),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
        ),
      ),
      home: ready ? Shell(store: store) : const Center(child: CircularProgressIndicator()),
    );
  }
}

class AppStore extends ChangeNotifier {
  static const String key = 'elegance_v21_data';
  static const List<String> supportedImageModels = ['gpt-image-1'];
  final List<Product> products = [];
  final List<Customer> customers = [];
  final List<OrderModel> orders = [];
  final List<InventoryMove> movements = [];
  final List<Publication> publications = [];
  final List<ActivityItem> activities = [];
  final List<AiGroup> aiGroups = [];
  int processedImages = 0;
  bool backendOnline = false;
  bool developerMode = true;
  String googleVisionKey = '';
  String openAiKey = '';
  String openAiImageModel = 'gpt-image-1';
  String openAiTextModel = 'gpt-5.6';

  void load() {
    final raw = html.window.localStorage[key];
    if (raw == null || raw.isEmpty) return;
    try {
      final map = jsonDecode(raw) as Map<String, dynamic>;
      products.addAll((map['products'] as List? ?? []).map((e) => Product.fromJson(e)));
      customers.addAll((map['customers'] as List? ?? []).map((e) => Customer.fromJson(e)));
      orders.addAll((map['orders'] as List? ?? []).map((e) => OrderModel.fromJson(e)));
      movements.addAll((map['movements'] as List? ?? []).map((e) => InventoryMove.fromJson(e)));
      publications.addAll((map['publications'] as List? ?? []).map((e) => Publication.fromJson(e)));
      activities.addAll((map['activities'] as List? ?? []).map((e) => ActivityItem.fromJson(e)));
      processedImages = (map['processedImages'] as num?)?.toInt() ?? 0;
      googleVisionKey = map['googleVisionKey']?.toString() ?? '';
      openAiKey = map['openAiKey']?.toString() ?? '';
      final storedImageModel = map['openAiImageModel']?.toString() ?? 'gpt-image-1';
      openAiImageModel = supportedImageModels.contains(storedImageModel)
          ? storedImageModel
          : supportedImageModels.first;
      openAiTextModel = map['openAiTextModel']?.toString() ?? 'gpt-5.6';
    } catch (_) {
      html.window.localStorage.remove(key);
    }
  }

  void save() {
    final map = {
      'products': products.map((e) => e.toJson()).toList(),
      'customers': customers.map((e) => e.toJson()).toList(),
      'orders': orders.map((e) => e.toJson()).toList(),
      'movements': movements.map((e) => e.toJson()).toList(),
      'publications': publications.map((e) => e.toJson()).toList(),
      'activities': activities.take(80).map((e) => e.toJson()).toList(),
      'processedImages': processedImages,
      'googleVisionKey': googleVisionKey,
      'openAiKey': openAiKey,
      'openAiImageModel': openAiImageModel,
      'openAiTextModel': openAiTextModel,
    };
    try {
      html.window.localStorage[key] = jsonEncode(map);
    } catch (_) {
      // The browser can reject very large image payloads. Metadata remains usable.
    }
    Future.microtask(() => _syncBackend(map));
    notifyListeners();
  }


  Future<void> syncFromBackend() async {
    try {
      final response = await http
          .get(Uri.parse('http://127.0.0.1:8000/api/state'))
          .timeout(const Duration(seconds: 5));
      if (response.statusCode != 200) return;
      final decoded = jsonDecode(response.body);
      if (decoded is! Map || decoded['state'] is! Map) return;
      final state = Map<String, dynamic>.from(decoded['state'] as Map);
      if (state.isEmpty || (state['products'] as List? ?? const []).isEmpty) return;
      products.clear(); customers.clear(); orders.clear(); movements.clear(); publications.clear(); activities.clear();
      products.addAll((state['products'] as List? ?? []).map((e) => Product.fromJson(e)));
      customers.addAll((state['customers'] as List? ?? []).map((e) => Customer.fromJson(e)));
      orders.addAll((state['orders'] as List? ?? []).map((e) => OrderModel.fromJson(e)));
      movements.addAll((state['movements'] as List? ?? []).map((e) => InventoryMove.fromJson(e)));
      publications.addAll((state['publications'] as List? ?? []).map((e) => Publication.fromJson(e)));
      activities.addAll((state['activities'] as List? ?? []).map((e) => ActivityItem.fromJson(e)));
      processedImages = (state['processedImages'] as num?)?.toInt() ?? processedImages;
      try { html.window.localStorage[key] = jsonEncode(state); } catch (_) {}
      notifyListeners();
    } catch (_) {
      // El sistema continúa con la copia local si el backend aún no está listo.
    }
  }

  Future<void> _syncBackend(Map<String, dynamic> state) async {
    final safeState = Map<String, dynamic>.from(state)
      ..remove('googleVisionKey')
      ..remove('openAiKey');
    try {
      await http.post(
        Uri.parse('http://127.0.0.1:8000/api/state'),
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode({'state': safeState}),
      ).timeout(const Duration(seconds: 8));
    } catch (_) {
      // Queda pendiente en localStorage y se volverá a sincronizar en el siguiente cambio.
    }
  }

  void log(String text, IconData icon) {
    activities.insert(0, ActivityItem(text: text, time: DateTime.now(), iconCode: icon.codePoint));
    if (activities.length > 80) activities.removeRange(80, activities.length);
  }

  void addProduct(Product p) {
    products.add(p);
    log('Producto creado: ${p.title}', Icons.inventory_2_outlined);
    save();
  }

  void updateProduct(Product p) {
    final i = products.indexWhere((x) => x.id == p.id);
    if (i >= 0) products[i] = p;
    log('Producto actualizado: ${p.title}', Icons.edit_outlined);
    save();
    Future.microtask(() => _teachRecognition(p));
  }

  Future<void> _teachRecognition(Product p) async {
    final image = p.imageBase64 ?? (p.galleryBase64.isNotEmpty ? p.galleryBase64.first : null);
    if (image == null || image.isEmpty || p.brand.trim().isEmpty || p.model.trim().isEmpty) return;
    try {
      await http.post(
        Uri.parse('http://127.0.0.1:8000/api/recognition/learn'),
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode({
          'image_base64': image,
          'brand': p.brand,
          'model': p.model,
          'title': p.title,
          'sku': p.sku,
        }),
      ).timeout(const Duration(seconds: 20));
    } catch (_) {
      // La corrección queda guardada aunque el motor de aprendizaje esté temporalmente fuera de línea.
    }
  }

  void deleteProduct(String id) {
    final item = products.where((x) => x.id == id).firstOrNull;
    products.removeWhere((x) => x.id == id);
    if (item != null) log('Producto eliminado: ${item.title}', Icons.delete_outline);
    save();
  }

  void adjustStock(Product p, int delta, String reason) {
    p.stock = (p.stock + delta).clamp(0, 999999).toInt();
    movements.insert(0, InventoryMove(
      id: uid(), productId: p.id, productTitle: p.title, delta: delta,
      reason: reason, time: DateTime.now(),
    ));
    log('${delta >= 0 ? 'Entrada' : 'Salida'} de inventario: ${p.title} (${delta.abs()})', Icons.swap_vert);
    save();
  }

  void addCustomer(Customer c) {
    customers.add(c);
    log('Cliente registrado: ${c.name}', Icons.person_add_alt_1);
    save();
  }

  void addOrder(OrderModel o) {
    orders.add(o);
    for (final line in o.lines) {
      final p = products.where((x) => x.id == line.productId).firstOrNull;
      if (p != null) adjustStock(p, -line.quantity, 'Pedido ${o.folio}');
    }
    log('Pedido creado: ${o.folio}', Icons.shopping_bag_outlined);
    save();
  }

  void updateOrderStatus(OrderModel o, String status) {
    o.status = status;
    log('${o.folio}: $status', Icons.local_shipping_outlined);
    save();
  }

  void setDeveloperMode(bool value) {
    developerMode = value;
    notifyListeners();
  }

  void addPublication(Publication p) {
    publications.add(p);
    log('Publicación preparada: ${p.productTitle}', Icons.campaign_outlined);
    save();
  }

  void updatePublication(Publication p) {
    final i = publications.indexWhere((x) => x.id == p.id);
    if (i >= 0) publications[i] = p;
    log('Publicación actualizada: ${p.productTitle}', Icons.photo_library_outlined);
    save();
  }

  void prepareProductForPublications(Product product) {
    final existing = publications.where((x) => x.productId == product.id).firstOrNull;
    final images = <String>[
      if (product.imageBase64 != null && product.imageBase64!.isNotEmpty) product.imageBase64!,
      ...product.galleryBase64,
    ].toSet().toList();
    final copy = '✨ ${product.title}\nMarca: ${product.brand}\nColor: ${product.color}\nConsulta tallas, precio y disponibilidad por WhatsApp.\n\nLa elegancia se lleva al nacer y permanece en tus pies.';
    if (existing != null) {
      existing.imagesBase64 = images;
      existing.imageBase64 = images.isEmpty ? null : images.first;
      existing.status = 'Lista para elegir fotos';
      updatePublication(existing);
      return;
    }
    addPublication(Publication(
      id: uid(),
      productId: product.id,
      productTitle: product.title,
      channel: 'Multicanal',
      copy: copy,
      status: 'Lista para elegir fotos',
      createdAt: DateTime.now(),
      imageBase64: images.isEmpty ? null : images.first,
      imagesBase64: images,
    ));
  }

  void approveAiGroup(AiGroup g) {
    if (g.approved) return;
    final cover = (g.imageBase64 != null && g.imageBase64!.isNotEmpty)
        ? g.imageBase64
        : (g.galleryBase64.isNotEmpty ? g.galleryBase64.first : null);
    if (cover == null || cover.isEmpty) {
      log('No se creó ${g.title}: el grupo no contiene una fotografía válida.', Icons.warning_amber_outlined);
      notifyListeners();
      return;
    }

    final cleanBrand = g.brand.trim().isEmpty || g.brand == 'Unknown' ? 'Calzado' : g.brand.trim();
    final cleanModel = g.model.trim().isEmpty || g.model.contains('Other') ? '' : g.model.trim();
    final cleanColor = g.color.trim();
    final proposedTitle = g.title.trim();
    final automaticTitle = [cleanBrand, if (cleanModel.isEmpty) 'modelo pendiente' else cleanModel, cleanColor].where((x) => x.isNotEmpty).join(' ').replaceAll(RegExp(r'\s+'), ' ').trim();
    g.title = proposedTitle.isNotEmpty && !proposedTitle.toLowerCase().contains('modelo por revisar')
        ? proposedTitle
        : (automaticTitle.isEmpty ? '$cleanBrand modelo por revisar' : automaticTitle);

    final normalized = g.title.toLowerCase().replaceAll(RegExp(r'[^a-z0-9áéíóúüñ]+'), ' ').trim();
    // Solo unir vistas cuando existe una identidad suficientemente específica.
    // Antes, todos los “Sin identificar Gris/Café” se fusionaban y por eso
    // desaparecían productos del catálogo.
    final canMergeByIdentity = cleanBrand != 'Calzado' && cleanBrand != 'Sin identificar' && cleanModel.isNotEmpty;
    final existing = canMergeByIdentity
        ? products.where((p) => p.model.trim().isNotEmpty && p.title.toLowerCase().replaceAll(RegExp(r'[^a-z0-9áéíóúüñ]+'), ' ').trim() == normalized).firstOrNull
        : null;
    if (existing != null) {
      existing.galleryBase64 = <String>{...existing.galleryBase64, ...g.galleryBase64}.toList();
      existing.imageBase64 ??= cover;
      existing.identificationConfidence = [existing.identificationConfidence, g.modelConfidence, g.brandConfidence].reduce((a, b) => a > b ? a : b);
      g.approved = true;
      updateProduct(existing);
      prepareProductForPublications(existing);
      log('Auto Sync agregó nuevas vistas a ${existing.title}.', Icons.collections_outlined);
      save();
      return;
    }

    g.approved = true;
    final product = Product(
      id: uid(),
      sku: g.sku.trim().isNotEmpty ? g.sku.trim() : (cleanModel.isEmpty ? 'PEND-${DateTime.now().millisecondsSinceEpoch}-${g.id}' : generateSku(cleanBrand, cleanModel)),
      title: g.title,
      brand: cleanBrand,
      model: cleanModel,
      color: cleanColor,
      price: 0,
      stock: 0,
      sizes: '',
      imageBase64: cover,
      galleryBase64: g.galleryBase64,
      scenarioApplied: false,
      identificationConfidence: [g.modelConfidence, g.brandConfidence, g.confidence].reduce((a, b) => a > b ? a : b),
      createdAt: DateTime.now(),
      notes: g.needsReview
          ? 'Creado automáticamente con identificación local; revisar el modelo exacto cuando sea necesario.'
          : 'Creado automáticamente por Auto Sync con identificación local.',
    );
    addProduct(product);
    prepareProductForPublications(product);
    log('Auto Sync publicó automáticamente ${product.title} en Catálogo, Inventario y Publicaciones.', Icons.verified_outlined);
    save();
  }

  double get totalSales => orders.where((o) => o.status != 'Cancelado').fold(0, (a, b) => a + b.total);
  int get totalStock => products.fold(0, (a, b) => a + b.stock);
  int get activeOrders => orders.where((o) => o.status != 'Entregado' && o.status != 'Cancelado').length;
}

extension FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}

class Product {
  Product({
    required this.id,
    required this.sku,
    required this.title,
    required this.brand,
    required this.model,
    required this.color,
    required this.price,
    required this.stock,
    required this.sizes,
    required this.createdAt,
    this.imageBase64,
    this.galleryBase64 = const [],
    this.notes = '',
    this.scenarioApplied = false,
    this.identificationConfidence = 0,
    this.category = 'Calzado',
    this.subcategory = 'Sneakers',
    this.categoryConfidence = 0,
    this.categorySource = 'legacy',
    this.gender = 'Unisex',
    this.primaryColor = 'Sin identificar',
    this.secondaryColors = const [],
    this.season = 'Todo el año',
  });

  String id, sku, title, brand, model, color, sizes, notes, category, subcategory, categorySource, gender, primaryColor, season;
  List<String> secondaryColors;
  double price, identificationConfidence, categoryConfidence;
  int stock;
  DateTime createdAt;
  String? imageBase64;
  List<String> galleryBase64;
  bool scenarioApplied;

  Map<String, dynamic> toJson() => {
    'id': id,
    'sku': sku,
    'title': title,
    'brand': brand,
    'model': model,
    'color': color,
    'price': price,
    'stock': stock,
    'sizes': sizes,
    'notes': notes,
    'createdAt': createdAt.toIso8601String(),
    'imageBase64': imageBase64,
    'galleryBase64': galleryBase64,
    'scenarioApplied': scenarioApplied,
    'identificationConfidence': identificationConfidence,
    'category': category,
    'subcategory': subcategory,
    'categoryConfidence': categoryConfidence,
    'categorySource': categorySource,
    'gender': gender,
    'primaryColor': primaryColor,
    'secondaryColors': secondaryColors,
    'season': season,
  };

  factory Product.fromJson(dynamic j) => Product(
    id: j['id'],
    sku: j['sku'] ?? '',
    title: j['title'] ?? '',
    brand: j['brand'] ?? '',
    model: j['model'] ?? '',
    color: j['color'] ?? '',
    price: (j['price'] as num?)?.toDouble() ?? 0,
    stock: (j['stock'] as num?)?.toInt() ?? 0,
    sizes: j['sizes'] ?? '',
    notes: j['notes'] ?? '',
    createdAt: DateTime.tryParse(j['createdAt'] ?? '') ?? DateTime.now(),
    imageBase64: j['imageBase64'],
    galleryBase64: (j['galleryBase64'] as List? ?? const []).map((e) => e.toString()).toList(),
    scenarioApplied: j['scenarioApplied'] == true,
    identificationConfidence: (j['identificationConfidence'] as num?)?.toDouble() ?? 0,
    category: j['category']?.toString() ?? 'Calzado',
    subcategory: j['subcategory']?.toString() ?? 'Sneakers',
    categoryConfidence: (j['categoryConfidence'] as num?)?.toDouble() ?? 0,
    categorySource: j['categorySource']?.toString() ?? 'legacy',
    gender: j['gender']?.toString() ?? 'Unisex',
    primaryColor: j['primaryColor']?.toString() ?? j['color']?.toString() ?? 'Sin identificar',
    secondaryColors: (j['secondaryColors'] as List? ?? const []).map((e) => e.toString()).toList(),
    season: j['season']?.toString() ?? 'Todo el año',
  );
}

class Customer {
  Customer({required this.id, required this.name, this.phone='', this.address='', this.notes=''});
  String id, name, phone, address, notes;
  Map<String,dynamic> toJson()=>{'id':id,'name':name,'phone':phone,'address':address,'notes':notes};
  factory Customer.fromJson(dynamic j)=>Customer(id:j['id'],name:j['name']??'',phone:j['phone']??'',address:j['address']??'',notes:j['notes']??'');
}

class OrderLine {
  OrderLine({required this.productId, required this.title, required this.quantity, required this.unitPrice});
  String productId,title; int quantity; double unitPrice;
  double get subtotal=>quantity*unitPrice;
  Map<String,dynamic> toJson()=>{'productId':productId,'title':title,'quantity':quantity,'unitPrice':unitPrice};
  factory OrderLine.fromJson(dynamic j)=>OrderLine(productId:j['productId'],title:j['title'],quantity:(j['quantity'] as num).toInt(),unitPrice:(j['unitPrice'] as num).toDouble());
}

class OrderModel {
  OrderModel({required this.id,required this.folio,required this.customerId,required this.customerName,required this.lines,required this.deposit,required this.status,required this.createdAt});
  String id,folio,customerId,customerName,status; List<OrderLine> lines; double deposit; DateTime createdAt;
  double get total=>lines.fold(0,(a,b)=>a+b.subtotal); double get balance=>total-deposit;
  Map<String,dynamic> toJson()=>{'id':id,'folio':folio,'customerId':customerId,'customerName':customerName,'lines':lines.map((e)=>e.toJson()).toList(),'deposit':deposit,'status':status,'createdAt':createdAt.toIso8601String()};
  factory OrderModel.fromJson(dynamic j)=>OrderModel(id:j['id'],folio:j['folio'],customerId:j['customerId']??'',customerName:j['customerName']??'',lines:(j['lines'] as List).map((e)=>OrderLine.fromJson(e)).toList(),deposit:(j['deposit'] as num?)?.toDouble()??0,status:j['status']??'Pendiente',createdAt:DateTime.tryParse(j['createdAt']??'')??DateTime.now());
}

class InventoryMove {
  InventoryMove({required this.id,required this.productId,required this.productTitle,required this.delta,required this.reason,required this.time});
  String id,productId,productTitle,reason; int delta; DateTime time;
  Map<String,dynamic> toJson()=>{'id':id,'productId':productId,'productTitle':productTitle,'delta':delta,'reason':reason,'time':time.toIso8601String()};
  factory InventoryMove.fromJson(dynamic j)=>InventoryMove(id:j['id'],productId:j['productId'],productTitle:j['productTitle'],delta:(j['delta'] as num).toInt(),reason:j['reason'],time:DateTime.tryParse(j['time'])??DateTime.now());
}

class Publication {
  Publication({required this.id,required this.productId,required this.productTitle,required this.channel,required this.copy,required this.status,required this.createdAt,this.imageBase64,this.imagesBase64=const []});
  String id,productId,productTitle,channel,copy,status; DateTime createdAt; String? imageBase64; List<String> imagesBase64;
  Map<String,dynamic> toJson()=>{'id':id,'productId':productId,'productTitle':productTitle,'channel':channel,'copy':copy,'status':status,'createdAt':createdAt.toIso8601String(),'imageBase64':imageBase64,'imagesBase64':imagesBase64};
  factory Publication.fromJson(dynamic j)=>Publication(id:j['id'],productId:j['productId'],productTitle:j['productTitle'],channel:j['channel'],copy:j['copy'],status:j['status'],createdAt:DateTime.tryParse(j['createdAt'])??DateTime.now(),imageBase64:j['imageBase64'],imagesBase64:(j['imagesBase64'] as List? ?? const []).map((e)=>e.toString()).toList());
}

class ActivityItem {
  ActivityItem({required this.text,required this.time,required this.iconCode});
  String text; DateTime time; int iconCode;
  Map<String,dynamic> toJson()=>{'text':text,'time':time.toIso8601String(),'iconCode':iconCode};
  factory ActivityItem.fromJson(dynamic j)=>ActivityItem(text:j['text'],time:DateTime.tryParse(j['time'])??DateTime.now(),iconCode:(j['iconCode'] as num?)?.toInt()??Icons.bolt.codePoint);
}

class AiGroup {
  AiGroup({
    required this.id,
    required this.title,
    required this.brand,
    required this.model,
    required this.color,
    required this.count,
    required this.confidence,
    this.brandConfidence = 0,
    this.modelConfidence = 0,
    this.needsReview = false,
    this.imageBase64,
    this.galleryBase64 = const [],
    this.itemIndices = const [],
    this.duplicateCount = 0,
    this.scenarioApplied = false,
    this.approved = false,
    this.coverIndex = -1,
    this.webVerified = false,
    this.webConfigured = false,
    this.webConfidence = 0,
    this.verificationNote = '',
    this.sku = '',
    this.identificationMethod = '',
    this.identificationEvidence = const [],
  });

  int id, count, duplicateCount, coverIndex;
  String title, brand, model, color, sku, identificationMethod;
  List<String> identificationEvidence;
  double confidence, brandConfidence, modelConfidence, webConfidence;
  String? imageBase64;
  List<String> galleryBase64;
  List<int> itemIndices;
  bool approved, needsReview, scenarioApplied, webVerified, webConfigured;
  String verificationNote;
}


String uid()=>DateTime.now().microsecondsSinceEpoch.toString();
String normalizeEleganceBrand(String value) {
  final key = value.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');
  const aliases = <String, String>{
    'nike':'Nike','nike sportswear':'Nike','jordan':'Jordan','air jordan':'Jordan',
    'adidas':'Adidas','adidas originals':'Adidas','hugo boss':'Hugo Boss','hugoboss':'Hugo Boss','boss':'Hugo Boss',
    'new balance':'New Balance','newbalance':'New Balance','converse':'Converse','puma':'Puma','reebok':'Reebok',
    'vans':'Vans','under armour':'Under Armour','underarmour':'Under Armour','lacoste':'Lacoste',
    'gucci':'Gucci','louis vuitton':'Louis Vuitton','lv':'Louis Vuitton','balenciaga':'Balenciaga',
    'versace':'Versace','skechers':'Skechers','fila':'Fila','on running':'On Running'
  };
  if (key.isEmpty || const {'unknown','sin marca','sin identificar','por identificar','calzado'}.contains(key)) return 'Sin identificar';
  return aliases[key] ?? key.split(' ').map((w) => w.isEmpty ? w : '${w[0].toUpperCase()}${w.substring(1)}').join(' ');
}

String generateSku(String brand,String model){
  String clean(String x)=>x.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'),'');
  final b=clean(brand).padRight(3,'X').substring(0,3);
  final m=clean(model).padRight(4,'X').substring(0,4);
  return '$b-$m-${DateTime.now().millisecondsSinceEpoch.toString().substring(7)}';
}

Future<Uint8List?> composeWithBackend(
  XFile file,
  String brandTheme, {
  required String openAiKey,
  required String openAiImageModel,
  String productName = '',
}) async {
  final endpoint = openAiKey.trim().isEmpty ? 'compose' : 'compose-generative';
  final request = http.MultipartRequest('POST', Uri.parse('http://127.0.0.1:8000/$endpoint'));
  request.fields['brand_theme'] = brandTheme;
  request.fields['product_name'] = productName;
  request.fields['openai_api_key'] = openAiKey;
  request.fields['openai_image_model'] = openAiImageModel;
  request.files.add(http.MultipartFile.fromBytes('file', await file.readAsBytes(), filename: file.name));
  final streamed = await request.send().timeout(const Duration(minutes: 7));
  final response = await http.Response.fromStream(streamed);
  if (response.statusCode != 200) {
    throw Exception('Studio ${response.statusCode}: ${response.body}');
  }
  return response.bodyBytes;
}

class AutoProcessResult {
  AutoProcessResult({required this.brand,required this.model,required this.title,required this.webConfidence,required this.webConfigured,required this.webConfirmed,required this.publishable,required this.note,required this.finalImageBase64,required this.visualEngine,required this.visualNote});
  final String brand, model, title, note, finalImageBase64, visualEngine, visualNote;
  final double webConfidence;
  final bool webConfigured, webConfirmed, publishable;
}

Future<AutoProcessResult> autoProcessWithBackend({
  required XFile file,
  required String localBrand,
  required String localModel,
  required String color,
  required String googleVisionKey,
  required String openAiKey,
  required String openAiImageModel,
  required String openAiTextModel,
}) async {
  final request = http.MultipartRequest('POST', Uri.parse('http://127.0.0.1:8000/auto-process'));
  request.fields['local_brand'] = localBrand;
  request.fields['local_model'] = localModel;
  request.fields['color'] = color;
  request.fields['google_vision_api_key'] = googleVisionKey;
  request.fields['openai_api_key'] = openAiKey;
  request.fields['openai_image_model'] = openAiImageModel;
  request.fields['openai_text_model'] = openAiTextModel;
  request.files.add(http.MultipartFile.fromBytes('file', await file.readAsBytes(), filename: file.name));
  final streamed = await request.send().timeout(const Duration(minutes: 8));
  final response = await http.Response.fromStream(streamed);
  if (response.statusCode != 200) throw Exception(response.body);
  final data = jsonDecode(response.body) as Map<String,dynamic>;
  return AutoProcessResult(
    brand: data['brand']?.toString() ?? localBrand,
    model: data['model']?.toString() ?? localModel,
    title: data['title']?.toString() ?? '$localModel $color',
    webConfidence: (data['web_confidence'] as num?)?.toDouble() ?? 0,
    webConfigured: data['web_configured'] == true,
    webConfirmed: data['web_confirmed'] == true,
    publishable: data['publishable'] == true,
    note: data['verification_note']?.toString() ?? '',
    finalImageBase64: data['final_image_base64']?.toString() ?? '',
    visualEngine: data['visual_engine']?.toString() ?? 'unknown',
    visualNote: data['visual_note']?.toString() ?? '',
  );
}

class Shell extends StatefulWidget {
  const Shell({super.key,required this.store}); final AppStore store;
  @override State<Shell> createState()=>_ShellState();
}

class _ShellState extends State<Shell> {
  int index = 0;
  final devPages = const ['Inicio','Catálogo','Auto Sync','Studio','Inventario','Pedidos','Clientes','Publicaciones','Estadísticas','Configuración'];
  final devIcons = const [Icons.home_outlined,Icons.grid_view_rounded,Icons.sync,Icons.auto_fix_high,Icons.inventory_2_outlined,Icons.shopping_bag_outlined,Icons.groups_outlined,Icons.campaign_outlined,Icons.insights,Icons.settings_outlined];
  final clientPages = const ['Inicio','Catálogo'];
  final clientIcons = const [Icons.home_outlined, Icons.grid_view_rounded];

  @override
  void initState() {
    super.initState();
    widget.store.addListener(_refresh);
    _checkBackend();
  }

  @override
  void dispose() {
    widget.store.removeListener(_refresh);
    super.dispose();
  }

  void _refresh() { if (mounted) setState(() {}); }

  Future<void> _checkBackend() async {
    try {
      final r = await http.get(Uri.parse('http://127.0.0.1:8000/health')).timeout(const Duration(seconds: 3));
      widget.store.backendOnline = r.statusCode == 200;
    } catch (_) {
      widget.store.backendOnline = false;
    }
    if (mounted) setState(() {});
  }

  Future<void> _switchMode() async {
    if (widget.store.developerMode) {
      widget.store.setDeveloperMode(false);
      setState(() => index = 0);
      return;
    }
    final controller = TextEditingController();
    final accepted = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Modo desarrollador'),
        content: TextField(
          controller: controller,
          obscureText: true,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'PIN de administrador'),
          onSubmitted: (_) => Navigator.pop(c, controller.text == '2026'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(c, controller.text == '2026'), child: const Text('Desbloquear')),
        ],
      ),
    ) ?? false;
    if (accepted) {
      widget.store.setDeveloperMode(true);
      setState(() => index = 0);
    } else if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('PIN incorrecto.')));
    }
  }

  Widget current() {
    if (!widget.store.developerMode) {
      return index == 1
          ? CatalogPage(store: widget.store, clientMode: true)
          : ClientHome(store: widget.store, onCatalog: () => setState(() => index = 1));
    }
    switch (index) {
      case 0: return Dashboard(store: widget.store, onGo: (i) => setState(() => index = i));
      case 1: return CatalogPage(store: widget.store);
      case 2: return AutoSyncPage(store: widget.store);
      case 3: return StudioPage(store: widget.store);
      case 4: return InventoryPage(store: widget.store);
      case 5: return OrdersPage(store: widget.store);
      case 6: return CustomersPage(store: widget.store);
      case 7: return PublicationsPage(store: widget.store);
      case 8: return StatisticsPage(store: widget.store);
      default: return SettingsPage(store: widget.store, onCheck: _checkBackend);
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = widget.store.developerMode ? devPages : clientPages;
    final icons = widget.store.developerMode ? devIcons : clientIcons;
    if (index >= pages.length) index = 0;
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 950;
        return Scaffold(
          body: Stack(
            children: [
              const _AmbientBackground(),
              Row(
                children: [
                  if (!compact)
                    SideNav(
                      index: index,
                      pages: pages,
                      icons: icons,
                      developerMode: widget.store.developerMode,
                      onSwitchMode: _switchMode,
                      onTap: (i) => setState(() => index = i),
                    ),
                  Expanded(
                    child: SafeArea(
                      child: Padding(
                        padding: EdgeInsets.fromLTRB(compact ? 18 : 28, 18, 28, 18),
                        child: Column(
                          children: [
                            if (compact)
                              CompactTop(
                                index: index,
                                pages: pages,
                                icons: icons,
                                developerMode: widget.store.developerMode,
                                onSwitchMode: _switchMode,
                                onTap: (i) => setState(() => index = i),
                              ),
                            Expanded(
                              child: AnimatedSwitcher(
                                duration: const Duration(milliseconds: 260),
                                child: KeyedSubtree(key: ValueKey('${widget.store.developerMode}-$index'), child: current()),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class ClientHome extends StatelessWidget {
  const ClientHome({super.key, required this.store, required this.onCatalog});
  final AppStore store;
  final VoidCallback onCatalog;
  @override
  Widget build(BuildContext context) => ListView(
    children: [
      _PageHeader(title: 'elegance', subtitle: 'Catálogo premium para clientes.', store: store),
      const SizedBox(height: 18),
      GlassPanel(
        padding: EdgeInsets.zero,
        child: Container(
          constraints: const BoxConstraints(minHeight: 500),
          decoration: const BoxDecoration(
            borderRadius: BorderRadius.all(Radius.circular(22)),
            image: DecorationImage(image: AssetImage('assets/elegance_scenario_clean.png'), fit: BoxFit.cover),
          ),
          child: Container(
            padding: const EdgeInsets.all(36),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(22),
              gradient: const LinearGradient(colors: [Color(0xF000060A), Color(0x78000B12), Color(0xD000060A)]),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('elegance', style: TextStyle(color: ice, fontSize: 46, fontStyle: FontStyle.italic)),
                const SizedBox(height: 14),
                const Text('Descubre tu próximo modelo.', style: TextStyle(fontSize: 38, fontWeight: FontWeight.w900)),
                const SizedBox(height: 12),
                Text('${store.products.length} productos disponibles', style: const TextStyle(color: Colors.white70, fontSize: 17)),
                const SizedBox(height: 24),
                PrimaryButton(text: 'Explorar catálogo', icon: Icons.grid_view_rounded, onTap: onCatalog),
              ],
            ),
          ),
        ),
      ),
    ],
  );
}

class _AmbientBackground extends StatelessWidget {const _AmbientBackground();@override Widget build(BuildContext context)=>Positioned.fill(child:Container(decoration:const BoxDecoration(gradient:RadialGradient(center:Alignment(0.85,-0.8),radius:1.3,colors:[Color(0xFF063248),Color(0xFF020A0F),Color(0xFF010407)])),child:CustomPaint(painter:_GridPainter())));}
class _GridPainter extends CustomPainter{@override void paint(Canvas c,Size s){final p=Paint()..color=const Color(0x0B65D9FF)..strokeWidth=.6;for(double x=0;x<s.width;x+=70)c.drawLine(Offset(x,0),Offset(x,s.height),p);for(double y=0;y<s.height;y+=70)c.drawLine(Offset(0,y),Offset(s.width,y),p);}@override bool shouldRepaint(covariant CustomPainter oldDelegate)=>false;}

class SideNav extends StatelessWidget {
  const SideNav({super.key, required this.index, required this.pages, required this.icons, required this.onTap, required this.developerMode, required this.onSwitchMode});
  final int index;
  final List<String> pages;
  final List<IconData> icons;
  final ValueChanged<int> onTap;
  final bool developerMode;
  final VoidCallback onSwitchMode;
  @override
  Widget build(BuildContext context) => Container(
    width: 240,
    decoration: const BoxDecoration(color: Color(0xE6040B10), border: Border(right: BorderSide(color: line))),
    child: SafeArea(
      child: Column(
        children: [
          const SizedBox(height: 24), const Brand(), const SizedBox(height: 18), const Divider(color: line), const SizedBox(height: 12),
          Expanded(child: ListView.builder(padding: const EdgeInsets.symmetric(horizontal: 12), itemCount: pages.length, itemBuilder: (c,i) => Padding(padding: const EdgeInsets.only(bottom: 6), child: _NavButton(selected: i == index, label: pages[i], icon: icons[i], onTap: () => onTap(i))))),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 4, 14, 8),
            child: OutlinedButton.icon(
              onPressed: onSwitchMode,
              icon: Icon(developerMode ? Icons.visibility_outlined : Icons.admin_panel_settings_outlined),
              label: Text(developerMode ? 'Vista cliente' : 'Modo desarrollador'),
              style: OutlinedButton.styleFrom(minimumSize: const Size(double.infinity, 46), foregroundColor: ice, side: const BorderSide(color: line)),
            ),
          ),
          Padding(padding: const EdgeInsets.all(18), child: StatusPill(text: developerMode ? 'desarrollador activo' : 'modo cliente', ok: true)),
        ],
      ),
    ),
  );
}

class Brand extends StatelessWidget {const Brand({super.key});@override Widget build(BuildContext context)=>Row(children:[const SizedBox(width:20),Container(width:44,height:44,decoration:BoxDecoration(shape:BoxShape.circle,boxShadow:[BoxShadow(color:ice.withOpacity(.45),blurRadius:22)],border:Border.all(color:ice.withOpacity(.7))),child:const Icon(Icons.auto_awesome,color:ice)),const SizedBox(width:12),const Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('elegance',style:TextStyle(color:ice,fontSize:29,fontStyle:FontStyle.italic,fontWeight:FontWeight.w500)),Text('inteligencia visual para sneakers',style:TextStyle(color:muted,fontSize:9))])]);}
class _NavButton extends StatelessWidget {const _NavButton({required this.selected,required this.label,required this.icon,required this.onTap});final bool selected;final String label;final IconData icon;final VoidCallback onTap;@override Widget build(BuildContext context)=>Material(color:Colors.transparent,child:InkWell(onTap:onTap,borderRadius:BorderRadius.circular(14),child:AnimatedContainer(duration:const Duration(milliseconds:180),height:48,padding:const EdgeInsets.symmetric(horizontal:14),decoration:BoxDecoration(color:selected?const Color(0xCC0D3445):Colors.transparent,borderRadius:BorderRadius.circular(14),border:Border.all(color:selected?ice.withOpacity(.65):Colors.transparent),boxShadow:selected?[BoxShadow(color:ice.withOpacity(.12),blurRadius:16)]:null),child:Row(children:[Icon(icon,color:selected?ice:muted,size:21),const SizedBox(width:14),Text(label,style:TextStyle(color:selected?Colors.white:const Color(0xFFCDD8DE),fontWeight:selected?FontWeight.w700:FontWeight.w500)),const Spacer(),if(selected)const Icon(Icons.chevron_right,color:ice,size:20)]))));}
class CompactTop extends StatelessWidget {
  const CompactTop({super.key, required this.index, required this.pages, required this.icons, required this.onTap, required this.developerMode, required this.onSwitchMode});
  final int index;
  final List<String> pages;
  final List<IconData> icons;
  final ValueChanged<int> onTap;
  final bool developerMode;
  final VoidCallback onSwitchMode;
  @override
  Widget build(BuildContext context) => Row(
    children: [
      const Expanded(child: Brand()),
      IconButton(tooltip: developerMode ? 'Vista cliente' : 'Modo desarrollador', onPressed: onSwitchMode, icon: Icon(developerMode ? Icons.visibility_outlined : Icons.admin_panel_settings_outlined, color: ice)),
      PopupMenuButton<int>(icon: const Icon(Icons.menu, color: ice), color: const Color(0xFF071119), onSelected: onTap, itemBuilder: (c) => List.generate(pages.length, (i) => PopupMenuItem(value: i, child: Row(children: [Icon(icons[i], color: i == index ? ice : muted), const SizedBox(width: 10), Text(pages[i])])))),
    ],
  );
}


class Dashboard extends StatelessWidget {const Dashboard({super.key,required this.store,required this.onGo});final AppStore store;final ValueChanged<int> onGo;@override Widget build(BuildContext context)=>ListView(children:[_PageHeader(title:'elegance',subtitle:'Todo tu catálogo en un solo ecosistema.',store:store),const SizedBox(height:18),_Hero(store:store,onGo:onGo),const SizedBox(height:18),LayoutBuilder(builder:(c,k){final cols=k.maxWidth>1050?4:k.maxWidth>620?2:1;return GridView.count(shrinkWrap:true,physics:const NeverScrollableScrollPhysics(),crossAxisCount:cols,crossAxisSpacing:14,mainAxisSpacing:14,childAspectRatio:cols==1?3.2:2.15,children:[MetricCard(label:'Productos',value:'${store.products.length}',note:'${store.totalStock} piezas en stock',icon:Icons.inventory_2_outlined),MetricCard(label:'Imágenes procesadas',value:'${store.processedImages}',note:'IA y revisión',icon:Icons.image_search),MetricCard(label:'Pedidos activos',value:'${store.activeOrders}',note:'${store.orders.length} pedidos totales',icon:Icons.local_shipping_outlined),MetricCard(label:'Ventas',value:money(store.totalSales),note:'acumulado registrado',icon:Icons.payments_outlined)]);}),const SizedBox(height:18),GlassPanel(child:Wrap(alignment:WrapAlignment.spaceBetween,crossAxisAlignment:WrapCrossAlignment.center,runSpacing:12,children:[const Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('Accesos rápidos',style:TextStyle(fontSize:19,fontWeight:FontWeight.w800)),Text('Continúa con las tareas principales',style:TextStyle(color:muted))]),Wrap(spacing:10,runSpacing:10,children:[ActionButton(text:'Analizar imágenes',icon:Icons.image_search,onTap:()=>onGo(2)),ActionButton(text:'Abrir Studio',icon:Icons.auto_fix_high,onTap:()=>onGo(3)),ActionButton(text:'Ver catálogo',icon:Icons.grid_view,onTap:()=>onGo(1)),ActionButton(text:'Nuevo pedido',icon:Icons.shopping_bag_outlined,onTap:()=>onGo(5))])]))]);}
class _PageHeader extends StatelessWidget {const _PageHeader({required this.title,required this.subtitle,required this.store});final String title,subtitle;final AppStore store;@override Widget build(BuildContext context)=>Row(crossAxisAlignment:CrossAxisAlignment.start,children:[Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(title,style:TextStyle(color:title=='elegance'?ice:Colors.white,fontSize:36,fontStyle:title=='elegance'?FontStyle.italic:FontStyle.normal,fontWeight:FontWeight.w800)),Text(subtitle,style:const TextStyle(color:muted,fontSize:15))])),Wrap(spacing:8,children:[StatusPill(text:'IA ${store.backendOnline?'activa':'sin conexión'}',ok:store.backendOnline),StatusPill(text:'sync listo',ok:true)])]);}
class _Hero extends StatelessWidget {
  const _Hero({required this.store, required this.onGo});
  final AppStore store;
  final ValueChanged<int> onGo;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 410),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: ice.withOpacity(.38)),
        image: const DecorationImage(
          image: AssetImage('assets/elegance_mountain_scene.png'),
          fit: BoxFit.cover,
          alignment: Alignment.center,
        ),
      ),
      child: Container(
        padding: const EdgeInsets.all(30),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(28),
          gradient: const LinearGradient(
            colors: [Color(0xF500070B), Color(0xA9051D29), Color(0xD900080D)],
          ),
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final vertical = constraints.maxWidth < 850;
            final intro = Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Text(
                  'elegance',
                  style: TextStyle(color: ice, fontSize: 42, fontStyle: FontStyle.italic),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Tu boutique digital,\nsiempre en movimiento.',
                  style: TextStyle(fontSize: 37, height: 1.05, fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 18),
                const SizedBox(
                  width: 500,
                  child: Text(
                    'Analiza, organiza, edita, vende y publica tus modelos dentro de una experiencia visual única.',
                    style: TextStyle(color: Color(0xFFD7E3E8), fontSize: 16, height: 1.5),
                  ),
                ),
                const SizedBox(height: 22),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    PrimaryButton(text: 'Iniciar Auto Sync', icon: Icons.sync, onTap: () => onGo(2)),
                    ActionButton(text: 'Abrir Studio', icon: Icons.auto_fix_high, onTap: () => onGo(3)),
                  ],
                ),
              ],
            );
            final recent = GlassPanel(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('actividad reciente', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                  const Text('Movimientos reales del sistema', style: TextStyle(color: muted)),
                  const SizedBox(height: 14),
                  if (store.activities.isEmpty)
                    const _ActivityRow(
                      text: 'Aún no hay actividad. Crea un producto o analiza imágenes.',
                      icon: Icons.auto_awesome,
                    )
                  else
                    ...store.activities.take(4).map(
                      (a) => _ActivityRow(
                        text: a.text,
                        icon: IconData(a.iconCode, fontFamily: 'MaterialIcons'),
                      ),
                    ),
                ],
              ),
            );
            if (vertical) {
              return Column(
                children: [
                  Expanded(child: intro),
                  const SizedBox(height: 16),
                  recent,
                ],
              );
            }
            return Row(
              children: [
                Expanded(flex: 11, child: intro),
                const SizedBox(width: 20),
                Expanded(flex: 9, child: recent),
              ],
            );
          },
        ),
      ),
    );
  }
}
class _ActivityRow extends StatelessWidget {const _ActivityRow({required this.text,required this.icon});final String text;final IconData icon;@override Widget build(BuildContext context)=>Container(margin:const EdgeInsets.only(top:10),padding:const EdgeInsets.all(13),decoration:BoxDecoration(color:const Color(0xAA071722),borderRadius:BorderRadius.circular(14),border:Border.all(color:line)),child:Row(children:[Container(width:38,height:38,decoration:BoxDecoration(color:ice.withOpacity(.12),borderRadius:BorderRadius.circular(11)),child:Icon(icon,color:ice,size:20)),const SizedBox(width:12),Expanded(child:Text(text,style:const TextStyle(fontWeight:FontWeight.w600)))]));}

class CatalogPage extends StatefulWidget {
  const CatalogPage({super.key, required this.store, this.clientMode = false});
  final AppStore store;
  final bool clientMode;
  @override State<CatalogPage> createState() => _CatalogPageState();
}

class _CatalogPageState extends State<CatalogPage> {
  String q = '';
  String brand = 'Todas';
  String category = 'Todas';
  String subcategory = 'Todas';
  String gender = 'Todos';
  String season = 'Todas';
  String primaryColor = 'Todos';
  final Set<String> selectedIds = {};

  Future<void> _reorganizeCatalog() async {
    try {
      final response = await http.post(Uri.parse('http://127.0.0.1:8000/api/catalog/reorganize')).timeout(const Duration(seconds: 30));
      if (response.statusCode != 200) throw Exception('Error ${response.statusCode}');
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      await widget.store.syncFromBackend();
      if (!mounted) return;
      setState(() { if (brand != 'Todas' && !widget.store.products.any((p) => p.brand == brand)) brand = 'Todas'; });
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Catálogo actualizado: ${data['classified'] ?? 0} clasificados, ${data['preserved'] ?? 0} conservados y ${data['moved'] ?? 0} archivos organizados.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo reorganizar: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final brandCounts = <String, int>{};
    final categoryCounts = <String, int>{};
    final subcategoryCounts = <String, int>{};
    for (final p in widget.store.products) {
      brandCounts[p.brand] = (brandCounts[p.brand] ?? 0) + 1;
      categoryCounts[p.category] = (categoryCounts[p.category] ?? 0) + 1;
      if (category == 'Todas' || p.category == category) subcategoryCounts[p.subcategory] = (subcategoryCounts[p.subcategory] ?? 0) + 1;
    }
    final sortedBrands = brandCounts.keys.toList()..sort((a,b) { if (a == 'Sin identificar') return 1; if (b == 'Sin identificar') return -1; return a.compareTo(b); });
    final brands = ['Todas', ...sortedBrands];
    final categories = ['Todas', ...categoryCounts.keys.toList()..sort()];
    final subcategories = ['Todas', ...subcategoryCounts.keys.toList()..sort()];
    if (!subcategories.contains(subcategory)) subcategory = 'Todas';
    final genders = ['Todos', ...widget.store.products.map((p) => p.gender).toSet().toList()..sort()];
    final seasons = ['Todas', ...widget.store.products.map((p) => p.season).toSet().toList()..sort()];
    final colors = ['Todos', ...widget.store.products.map((p) => p.primaryColor).toSet().toList()..sort()];
    final normalizedQuery = q.trim().toLowerCase();
    final list = widget.store.products.where((p) => p.imageBase64 != null &&
      (category == 'Todas' || p.category == category) &&
      (subcategory == 'Todas' || p.subcategory == subcategory) &&
      (brand == 'Todas' || p.brand == brand) &&
      (gender == 'Todos' || p.gender == gender) &&
      (season == 'Todas' || p.season == season) &&
      (primaryColor == 'Todos' || p.primaryColor == primaryColor || p.secondaryColors.contains(primaryColor)) &&
      (normalizedQuery.isEmpty || ('${p.title} ${p.sku} ${p.brand} ${p.model} ${p.category} ${p.subcategory} ${p.gender} ${p.primaryColor} ${p.secondaryColors.join(' ')} ${p.season} ${p.notes}').toLowerCase().contains(normalizedQuery))).toList();
    return Column(
      children: [
        _PageHeader(title: 'Catálogo', subtitle: widget.clientMode ? 'Explora y abre cada producto en grande.' : 'Productos terminados por marca, precio, fotos, tallas y stock.', store: widget.store),
        const SizedBox(height: 18),
        Wrap(
          spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(width: 300, child: TextField(onChanged: (v) => setState(() => q = v), decoration: const InputDecoration(prefixIcon: Icon(Icons.search), labelText: 'Buscar producto o SKU'))),
            SizedBox(width: 180, child: DropdownButtonFormField<String>(value: category, items: categories.map((e) => DropdownMenuItem(value: e, child: Text(e == 'Todas' ? 'Categorías (${widget.store.products.length})' : '$e (${categoryCounts[e] ?? 0})'))).toList(), onChanged: (v) => setState(() { category = v!; subcategory = 'Todas'; }), decoration: const InputDecoration(labelText: 'Categoría'))),
            SizedBox(width: 190, child: DropdownButtonFormField<String>(value: subcategory, items: subcategories.map((e) => DropdownMenuItem(value: e, child: Text(e == 'Todas' ? 'Todas' : '$e (${subcategoryCounts[e] ?? 0})'))).toList(), onChanged: (v) => setState(() => subcategory = v!), decoration: const InputDecoration(labelText: 'Subcategoría'))),
            SizedBox(width: 180, child: DropdownButtonFormField<String>(value: brand, items: brands.map((e) => DropdownMenuItem(value: e, child: Text(e == 'Todas' ? 'Todas las marcas' : '$e (${brandCounts[e] ?? 0})'))).toList(), onChanged: (v) => setState(() => brand = v!), decoration: const InputDecoration(labelText: 'Marca'))),
            SizedBox(width: 160, child: DropdownButtonFormField<String>(value: gender, items: genders.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (v) => setState(() => gender = v!), decoration: const InputDecoration(labelText: 'Género'))),
            SizedBox(width: 160, child: DropdownButtonFormField<String>(value: primaryColor, items: colors.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (v) => setState(() => primaryColor = v!), decoration: const InputDecoration(labelText: 'Color'))),
            SizedBox(width: 160, child: DropdownButtonFormField<String>(value: season, items: seasons.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (v) => setState(() => season = v!), decoration: const InputDecoration(labelText: 'Temporada'))),
            if (!widget.clientMode) ...[
              const SizedBox(width: 12),
              PrimaryButton(text: 'Nuevo producto', icon: Icons.add, onTap: () => showProductDialog(context, widget.store)),
              const SizedBox(width: 10),
              ActionButton(text: 'Reorganizar catálogo', icon: Icons.folder_copy_outlined, onTap: _reorganizeCatalog),
              const SizedBox(width: 10),
              ActionButton(
                text: selectedIds.isEmpty ? 'Selecciona productos' : 'Enviar ${selectedIds.length} a Publicaciones',
                icon: Icons.campaign_outlined,
                onTap: selectedIds.isEmpty ? null : () {
                  for (final product in widget.store.products.where((p) => selectedIds.contains(p.id))) {
                    widget.store.prepareProductForPublications(product);
                  }
                  setState(() => selectedIds.clear());
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Productos enviados a Publicaciones para elegir las mejores fotos.')));
                },
              ),
            ],
          ],
        ),
        const SizedBox(height: 16),
        Expanded(
          child: list.isEmpty
              ? const EmptyState(icon: Icons.inventory_2_outlined, title: 'Catálogo vacío', text: 'Los productos aparecen automáticamente. Cuando el modelo no es seguro, se conserva únicamente la marca.')
              : GridView.builder(
                  gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 360, mainAxisExtent: 390, crossAxisSpacing: 14, mainAxisSpacing: 14),
                  itemCount: list.length,
                  itemBuilder: (c, i) {
                    final product = list[i];
                    final selected = selectedIds.contains(product.id);
                    return Stack(
                      children: [
                        Positioned.fill(child: ProductCard(
                          product: product,
                          clientMode: widget.clientMode,
                          onOpen: () => showProductDetail(context, product, clientMode: widget.clientMode),
                          onEdit: () => showProductDialog(context, widget.store, product: product),
                          onDelete: () => confirmDelete(context, widget.store, product),
                        )),
                        if (!widget.clientMode)
                          Positioned(
                            top: 8,
                            right: 8,
                            child: Material(
                              color: selected ? ice : Colors.black87,
                              shape: const CircleBorder(),
                              child: Checkbox(
                                value: selected,
                                activeColor: ice,
                                checkColor: Colors.black,
                                onChanged: (_) => setState(() => selected ? selectedIds.remove(product.id) : selectedIds.add(product.id)),
                              ),
                            ),
                          ),
                      ],
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class ProductCard extends StatelessWidget {
  const ProductCard({super.key, required this.product, required this.onOpen, required this.onEdit, required this.onDelete, required this.clientMode});
  final Product product;
  final VoidCallback onOpen, onEdit, onDelete;
  final bool clientMode;
  @override
  Widget build(BuildContext context) => GlassPanel(
    padding: EdgeInsets.zero,
    child: InkWell(
      onTap: onOpen,
      borderRadius: BorderRadius.circular(22),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Hero(
                tag: 'product-${product.id}',
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: product.imageBase64 == null
                      ? Container(color: const Color(0xFF0A151D), child: const Center(child: Icon(Icons.image_outlined, color: muted, size: 54)))
                      : Image.memory(base64Decode(product.imageBase64!), width: double.infinity, fit: BoxFit.cover),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(product.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text('${product.category} • ${product.subcategory}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: ice, fontSize: 12, fontWeight: FontWeight.w700)),
            const SizedBox(height: 3),
            Text('${product.brand} • ${product.color}', style: const TextStyle(color: muted)),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(child: Text(product.price > 0 ? money(product.price) : 'Precio por definir', style: const TextStyle(color: ice, fontWeight: FontWeight.w800))),
              Chip(label: Text('${product.stock} stock')),
            ]),
            Row(children: [
              const Icon(Icons.open_in_full, size: 16, color: ice), const SizedBox(width: 6), const Text('Abrir producto', style: TextStyle(color: ice)),
              const Spacer(),
              if (!clientMode) ...[
                IconButton(tooltip: 'Editar', onPressed: onEdit, icon: const Icon(Icons.edit_outlined)),
                IconButton(tooltip: 'Eliminar', onPressed: onDelete, icon: const Icon(Icons.delete_outline)),
              ],
            ]),
          ],
        ),
      ),
    ),
  );
}

Future<void> showProductDetail(BuildContext context, Product product, {required bool clientMode}) async {
  final images = <String>[if (product.imageBase64 != null) product.imageBase64!, ...product.galleryBase64].toSet().toList();
  int selected = 0;
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => StatefulBuilder(
      builder: (context, setLocal) => Dialog(
        insetPadding: const EdgeInsets.all(26),
        child: SizedBox(
          width: 1180,
          height: 760,
          child: Row(
            children: [
              Expanded(
                flex: 7,
                child: Container(
                  color: Colors.black,
                  child: Column(
                    children: [
                      Expanded(
                        child: images.isEmpty
                            ? const Center(child: Icon(Icons.image_outlined, size: 70, color: muted))
                            : InteractiveViewer(minScale: .7, maxScale: 5, child: Center(child: Image.memory(base64Decode(images[selected]), fit: BoxFit.contain))),
                      ),
                      if (images.length > 1)
                        SizedBox(
                          height: 100,
                          child: ListView.separated(
                            padding: const EdgeInsets.all(10),
                            scrollDirection: Axis.horizontal,
                            itemCount: images.length,
                            separatorBuilder: (_, __) => const SizedBox(width: 8),
                            itemBuilder: (_, i) => InkWell(
                              onTap: () => setLocal(() => selected = i),
                              child: Container(
                                width: 90,
                                decoration: BoxDecoration(borderRadius: BorderRadius.circular(10), border: Border.all(color: i == selected ? ice : line, width: i == selected ? 2 : 1)),
                                clipBehavior: Clip.antiAlias,
                                child: Image.memory(base64Decode(images[i]), fit: BoxFit.cover),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              Expanded(
                flex: 4,
                child: Padding(
                  padding: const EdgeInsets.all(26),
                  child: ListView(
                    children: [
                      Row(children: [Expanded(child: Text(product.title, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900))), IconButton(onPressed: () => Navigator.pop(dialogContext), icon: const Icon(Icons.close))]),
                      const SizedBox(height: 8),
                      Wrap(spacing: 8, runSpacing: 8, children: [Chip(label: Text(product.category)), Chip(label: Text(product.subcategory)), Chip(label: Text(product.brand)), Chip(label: Text(product.model)), Chip(label: Text(product.color)), Chip(label: Text(product.gender)), Chip(label: Text(product.season)), if (product.scenarioApplied) const Chip(avatar: Icon(Icons.auto_awesome, size: 16), label: Text('escenario elegance'))]),
                      const SizedBox(height: 18),
                      _DetailLine('Categoría', '${product.category} / ${product.subcategory}'),
                      _DetailLine('Género', product.gender),
                      _DetailLine('Colores', [product.primaryColor, ...product.secondaryColors].join(', ')),
                      _DetailLine('Temporada', product.season),
                      _DetailLine('SKU', product.sku),
                      _DetailLine('Tallas', product.sizes.isEmpty ? 'Por definir' : product.sizes),
                      _DetailLine('Precio', product.price > 0 ? money(product.price) : 'Por definir'),
                      _DetailLine('Stock', '${product.stock}'),
                      _DetailLine('Confianza IA', product.identificationConfidence > 0 ? '${(product.identificationConfidence * 100).toStringAsFixed(0)}%' : 'Revisión manual'),
                      const SizedBox(height: 18),
                      Text(product.notes.isEmpty ? 'Producto disponible en elegance.' : product.notes, style: const TextStyle(color: muted, height: 1.5)),
                      const SizedBox(height: 24),
                      if (clientMode)
                        PrimaryButton(text: 'Consultar por WhatsApp', icon: Icons.chat_outlined, onTap: () => html.window.open('https://wa.me/?text=${Uri.encodeComponent('Hola, me interesa ${product.title}')}', '_blank')),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _DetailLine extends StatelessWidget {
  const _DetailLine(this.label, this.value);
  final String label, value;
  @override Widget build(BuildContext context) => Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Row(children: [SizedBox(width: 110, child: Text(label, style: const TextStyle(color: muted))), Expanded(child: Text(value, style: const TextStyle(fontWeight: FontWeight.w700)))]));
}

Future<void> showProductDialog(
  BuildContext context,
  AppStore store, {
  Product? product,
}) async {
  final title = TextEditingController(text: product?.title ?? '');
  final brand = TextEditingController(text: product?.brand ?? '');
  final model = TextEditingController(text: product?.model ?? '');
  final color = TextEditingController(text: product?.color ?? '');
  final price = TextEditingController(text: product?.price.toStringAsFixed(0) ?? '');
  final stock = TextEditingController(text: product?.stock.toString() ?? '0');
  final sizes = TextEditingController(text: product?.sizes ?? '');
  final sku = TextEditingController(text: product?.sku ?? '');
  final notes = TextEditingController(text: product?.notes ?? '');
  String? image = product?.imageBase64;
  String selectedCategory = product?.category ?? 'Calzado';
  String selectedSubcategory = product?.subcategory ?? 'Sneakers';
  String selectedGender = product?.gender ?? 'Unisex';
  String selectedSeason = product?.season ?? 'Todo el año';
  final secondaryColors = TextEditingController(text: product?.secondaryColors.join(', ') ?? '');

  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return StatefulBuilder(
        builder: (context, setLocal) {
          return AlertDialog(
            title: Text(product == null ? 'Nuevo producto' : 'Editar producto'),
            content: SizedBox(
              width: 680,
              child: SingleChildScrollView(
                child: Column(
                  children: [
                    Wrap(
                      spacing: 12,
                      runSpacing: 12,
                      children: [
                        SizedBox(width: 320, child: TextField(controller: title, decoration: const InputDecoration(labelText: 'Nombre del producto'))),
                        SizedBox(width: 320, child: TextField(controller: sku, decoration: const InputDecoration(labelText: 'SKU'))),
                        SizedBox(width: 210, child: DropdownButtonFormField<String>(value: selectedCategory, items: universalCategories.keys.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (v) => setLocal(() { selectedCategory = v!; selectedSubcategory = universalCategories[selectedCategory]!.first; }), decoration: const InputDecoration(labelText: 'Categoría'))),
                        SizedBox(width: 210, child: DropdownButtonFormField<String>(value: selectedSubcategory, items: universalCategories[selectedCategory]!.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (v) => setLocal(() => selectedSubcategory = v!), decoration: const InputDecoration(labelText: 'Subcategoría'))),
                        SizedBox(width: 210, child: TextField(controller: brand, decoration: const InputDecoration(labelText: 'Marca'))),
                        SizedBox(width: 210, child: TextField(controller: model, decoration: const InputDecoration(labelText: 'Modelo'))),
                        SizedBox(width: 210, child: TextField(controller: color, decoration: const InputDecoration(labelText: 'Color principal'))),
                        SizedBox(width: 210, child: TextField(controller: secondaryColors, decoration: const InputDecoration(labelText: 'Colores secundarios'))),
                        SizedBox(width: 210, child: DropdownButtonFormField<String>(value: selectedGender, items: const ['Hombre','Mujer','Unisex','Niño','Niña'].map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (v) => setLocal(() => selectedGender = v!), decoration: const InputDecoration(labelText: 'Género'))),
                        SizedBox(width: 210, child: DropdownButtonFormField<String>(value: selectedSeason, items: const ['Primavera','Verano','Otoño','Invierno','Todo el año'].map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (v) => setLocal(() => selectedSeason = v!), decoration: const InputDecoration(labelText: 'Temporada'))),
                        SizedBox(width: 210, child: TextField(controller: price, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Precio'))),
                        SizedBox(width: 210, child: TextField(controller: stock, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Stock'))),
                        SizedBox(width: 210, child: TextField(controller: sizes, decoration: const InputDecoration(labelText: 'Tallas (ej. 3,4,5)'))),
                      ],
                    ),
                    const SizedBox(height: 12),
                    TextField(controller: notes, maxLines: 2, decoration: const InputDecoration(labelText: 'Notas')),
                    const SizedBox(height: 14),
                    Row(
                      children: [
                        PrimaryButton(
                          text: 'Seleccionar foto',
                          icon: Icons.add_photo_alternate_outlined,
                          onTap: () async {
                            final x = await ImagePicker().pickImage(
                              source: ImageSource.gallery,
                              imageQuality: 70,
                              maxWidth: 1000,
                            );
                            if (x == null) return;
                            final selectedBytes = await x.readAsBytes();
                            if (selectedBytes.length < 900000) {
                              setLocal(() => image = base64Encode(selectedBytes));
                            } else if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(content: Text('La foto es muy pesada. Selecciona una menor a 900 KB.')),
                              );
                            }
                          },
                        ),
                        const SizedBox(width: 12),
                        if (image != null)
                          ClipRRect(
                            borderRadius: BorderRadius.circular(12),
                            child: Image.memory(base64Decode(image!), width: 100, height: 75, fit: BoxFit.cover),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancelar')),
              FilledButton(
                onPressed: () {
                  if (title.text.trim().isEmpty) return;
                  final p = Product(
                    id: product?.id ?? uid(),
                    sku: sku.text.trim().isEmpty ? generateSku(brand.text, model.text) : sku.text.trim(),
                    title: title.text.trim(),
                    brand: normalizeEleganceBrand(brand.text),
                    model: model.text.trim(),
                    color: color.text.trim(),
                    price: double.tryParse(price.text) ?? 0,
                    stock: int.tryParse(stock.text) ?? 0,
                    sizes: sizes.text.trim(),
                    notes: notes.text.trim(),
                    createdAt: product?.createdAt ?? DateTime.now(),
                    imageBase64: image,
                    galleryBase64: product?.galleryBase64 ?? const [],
                    scenarioApplied: product?.scenarioApplied ?? false,
                    identificationConfidence: product?.identificationConfidence ?? 0,
                    category: selectedCategory,
                    subcategory: selectedSubcategory,
                    categoryConfidence: 1.0,
                    categorySource: 'manual',
                    gender: selectedGender,
                    primaryColor: color.text.trim().isEmpty ? 'Sin identificar' : color.text.trim(),
                    secondaryColors: secondaryColors.text.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList(),
                    season: selectedSeason,
                  );
                  if (product == null) {
                    store.addProduct(p);
                  } else {
                    store.updateProduct(p);
                  }
                  Navigator.pop(dialogContext);
                },
                child: const Text('Guardar'),
              ),
            ],
          );
        },
      );
    },
  );
}

Future<void> confirmDelete(BuildContext context,AppStore store,Product p)async{final ok=await showDialog<bool>(context:context,builder:(c)=>AlertDialog(title:const Text('Eliminar producto'),content:Text('¿Eliminar ${p.title}?'),actions:[TextButton(onPressed:()=>Navigator.pop(c,false),child:const Text('Cancelar')),FilledButton(onPressed:()=>Navigator.pop(c,true),child:const Text('Eliminar'))]))??false;if(ok)store.deleteProduct(p.id);}

class AutoSyncPage extends StatefulWidget {
  const AutoSyncPage({super.key, required this.store});
  final AppStore store;

  @override
  State<AutoSyncPage> createState() => _AutoSyncPageState();
}

class _AutoSyncPageState extends State<AutoSyncPage> {
  List<XFile> files = [];
  bool busy = false;
  bool autoPublish = true;
  String message = 'Selecciona todas las fotografías del lote.';
  List<String> duplicateWarnings = [];
  final Set<int> processingGroupIds = {};

  Future<void> analyze() async {
    setState(() { busy = true; message = 'Analizando todas las imágenes...'; duplicateWarnings = []; });
    try {
      final request = http.MultipartRequest('POST', Uri.parse('http://127.0.0.1:8000/group?eps=0.075&min_samples=1'));
      for (var fileIndex = 0; fileIndex < files.length; fileIndex++) {
        final x = files[fileIndex];
        final bytes = await x.readAsBytes();
        request.files.add(http.MultipartFile.fromBytes('files', bytes, filename: x.name));
        if (mounted && (fileIndex % 3 == 0 || fileIndex == files.length - 1)) {
          setState(() => message = 'Preparando ${fileIndex + 1} de ${files.length} imágenes...');
          await Future<void>.delayed(Duration.zero);
        }
      }
      if (mounted) setState(() => message = 'Analizando el lote en segundo plano... Puedes dejar esta pestaña abierta.');
      final streamed = await request.send().timeout(const Duration(minutes: 20));
      final response = await http.Response.fromStream(streamed);
      if (response.statusCode != 200) throw Exception(response.body);
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      widget.store.aiGroups.clear();

      final metadata = (data['images'] as List? ?? const []);
      for (final raw in metadata) {
        final m = Map<String, dynamic>.from(raw as Map);
        if (m['duplicate'] == true) {
          duplicateWarnings.add('${m['filename']} es un duplicado exacto de la imagen ${(m['duplicate_of'] as num?)?.toInt() ?? 0 + 1}.');
        }
      }

      for (final raw in (data['groups'] as List? ?? const [])) {
        final g = Map<String, dynamic>.from(raw as Map);
        final cover = (g['cover_index'] as num).toInt();
        final items = (g['items'] as List? ?? const []).map((e) => (Map<String, dynamic>.from(e as Map)['index'] as num).toInt()).toList();
        // Mantener el listado ligero: solo se carga la portada. Las demás vistas
        // permanecen en el lote y se procesan en backend, evitando decenas de MB
        // en Base64 dentro del navegador.
        final gallery = <String>[];
        String? finalImage;
        if (cover >= 0 && cover < files.length) {
          final coverBytes = await files[cover].readAsBytes();
          if (coverBytes.length < 1100000) {
            finalImage = base64Encode(coverBytes);
            gallery.add(finalImage);
          }
        }
        await Future<void>.delayed(Duration.zero);
        const bool scenarioApplied = false;

        final group = AiGroup(
          id: (g['group_id'] as num).toInt(),
          title: g['suggested_title'] as String? ?? '${g['model_family'] ?? 'Modelo por revisar'} ${g['dominant_color'] ?? ''}',
          brand: g['brand'] as String? ?? 'Sin marca',
          model: g['model_family'] as String? ?? '',
          color: g['dominant_color'] as String? ?? '',
          count: (g['count'] as num).toInt(),
          confidence: (g['average_confidence'] as num?)?.toDouble() ?? 0,
          brandConfidence: (g['brand_confidence'] as num?)?.toDouble() ?? 0,
          modelConfidence: (g['model_confidence'] as num?)?.toDouble() ?? 0,
          needsReview: g['needs_manual_review'] == true,
          imageBase64: finalImage,
          galleryBase64: gallery,
          itemIndices: items,
          duplicateCount: duplicateWarnings.length,
          scenarioApplied: scenarioApplied,
          coverIndex: cover,
          sku: g['sku']?.toString() ?? '',
          identificationMethod: g['identification_method']?.toString() ?? '',
          identificationEvidence: (g['identification_evidence'] as List? ?? const []).map((e) => e.toString()).toList(),
        );
        widget.store.aiGroups.add(group);
      }
      widget.store.processedImages += (data['images_received'] as num).toInt();
      widget.store.log('Auto Sync: ${data['images_received']} imágenes, ${data['groups_found']} productos, ${data['duplicate_images']} duplicados advertidos.', Icons.sync);
      widget.store.save();
      setState(() {
        message = '${data['images_received']} imágenes recibidas • ${data['unique_images']} conservadas • ${data['groups_found']} productos detectados. Publicando automáticamente...';
      });
      if (autoPublish) {
        final pendingAutoPublish = widget.store.aiGroups.where((g) => !g.approved).toList();
        for (var publishIndex = 0; publishIndex < pendingAutoPublish.length; publishIndex++) {
          widget.store.approveAiGroup(pendingAutoPublish[publishIndex]);
          if (publishIndex % 4 == 0) await Future<void>.delayed(Duration.zero);
        }
      }
      if (mounted) {
        setState(() {
          message = '${data['images_received']} imágenes procesadas • ${data['groups_found']} productos creados automáticamente en Catálogo e Inventario.';
        });
      }
    } catch (error) {
      setState(() => message = 'Error: $error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> processOneGroup(AiGroup group, {bool publishWhenConfirmed = true}) async {
    if (processingGroupIds.contains(group.id)) return;
    setState(() => processingGroupIds.add(group.id));
    try {
      group.imageBase64 ??= group.galleryBase64.isNotEmpty ? group.galleryBase64.first : null;
      group.scenarioApplied = false;
      group.webConfigured = false;
      group.webVerified = false;
      group.webConfidence = 0;
      group.verificationNote = group.needsReview
          ? 'Identificación local provisional. El producto se publicó para no detener el catálogo y puede corregirse después.'
          : 'Identificación local completada sin API de pago.';
      if (publishWhenConfirmed) widget.store.approveAiGroup(group); else widget.store.save();
    } finally {
      if (mounted) setState(() => processingGroupIds.remove(group.id));
    }
  }

  Future<void> processAllGroups({bool publishWhenConfirmed = true}) async {
    final pending = widget.store.aiGroups.where((g) => !g.approved).toList();
    const parallelism = 2; // Evita saturar la API y reduce casi a la mitad el tiempo del lote.
    for (var i = 0; i < pending.length; i += parallelism) {
      final batch = pending.skip(i).take(parallelism).toList();
      if (mounted) {
        setState(() => message = 'Procesando ${i + 1}-${i + batch.length} de ${pending.length}: identificación, escenario y catálogo...');
      }
      await Future.wait(batch.map((group) => processOneGroup(group, publishWhenConfirmed: publishWhenConfirmed)));
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    children: [
      _PageHeader(title: 'Auto Sync', subtitle: 'Sube desde la PC o conecta tu S26 por QR. La computadora recibe, comprime, identifica y publica en segundo plano, sin APIs de pago.', store: widget.store),
      const SizedBox(height: 18),
      GlassPanel(
        child: Column(
          children: [
            Row(children: [
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(message, style: const TextStyle(fontSize: 16)), const SizedBox(height: 6), Text('${files.length} archivos seleccionados. Ninguna imagen diferente se elimina.', style: const TextStyle(color: muted))])),
              Switch(value: autoPublish, onChanged: busy ? null : (v) => setState(() => autoPublish = v)),
              const Text('Crear y publicar automáticamente'),
              const SizedBox(width: 14),
              ActionButton(
                text: 'Conectar S26 por QR',
                icon: Icons.qr_code_2,
                onTap: busy ? null : () => html.window.open('http://127.0.0.1:8000/connect', '_blank'),
              ),
              const SizedBox(width: 10),
              ActionButton(
                text: 'Actualizar bandeja móvil',
                icon: Icons.refresh,
                onTap: busy ? null : () async {
                  await widget.store.syncFromBackend();
                  if (mounted) setState(() => message = 'Bandeja móvil sincronizada con Catálogo.');
                },
              ),
              const SizedBox(width: 10),
              PrimaryButton(text: 'Seleccionar todas', icon: Icons.photo_library_outlined, onTap: busy ? null : () async {
                final picked = await ImagePicker().pickMultiImage(maxWidth: 1800, maxHeight: 1800, imageQuality: 82);
                setState(() { files = picked; message = '${picked.length} imágenes listas para analizar.'; });
              }),
              const SizedBox(width: 10),
              PrimaryButton(text: busy ? 'Procesando...' : 'Ejecutar flujo', icon: busy ? Icons.hourglass_top : Icons.auto_awesome, onTap: busy || files.isEmpty ? null : analyze),
              if (widget.store.aiGroups.isNotEmpty) ...[
                const SizedBox(width: 10),
                ActionButton(
                  text: 'Procesar y publicar todo',
                  icon: Icons.verified_outlined,
                  onTap: busy ? null : () async {
                    setState(() => busy = true);
                    await processAllGroups(publishWhenConfirmed: true);
                    if (mounted) setState(() => busy = false);
                  },
                ),
              ],
            ]),
            if (busy) ...[const SizedBox(height: 14), const LinearProgressIndicator(), const SizedBox(height: 8), const Text('1. duplicados exactos → 2. agrupación → 3. identificación local → 4. título → 5. catálogo', style: TextStyle(color: muted))],
            if (duplicateWarnings.isNotEmpty) ...[
              const SizedBox(height: 14),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                leading: const Icon(Icons.copy_all_outlined, color: Colors.amber),
                title: Text('${duplicateWarnings.length} duplicados exactos omitidos automáticamente'),
                children: duplicateWarnings.map((e) => ListTile(dense: true, leading: const Icon(Icons.warning_amber, size: 18), title: Text(e))).toList(),
              ),
            ],
          ],
        ),
      ),
      const SizedBox(height: 16),
      Expanded(
        child: widget.store.aiGroups.isEmpty
            ? const EmptyState(icon: Icons.sync, title: 'Sin productos procesados', text: 'Selecciona el lote completo y ejecuta el flujo.')
            : ListView.separated(
                itemCount: widget.store.aiGroups.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (context, i) {
                  final g = widget.store.aiGroups[i];
                  return GlassPanel(
                    child: Row(
                      children: [
                        Builder(builder: (context) {
                          final preview = g.imageBase64 ?? (g.galleryBase64.isNotEmpty ? g.galleryBase64.first : null);
                          return InkWell(
                            onTap: preview == null ? null : () => showDialog<void>(context: context, builder: (_) => Dialog(child: InteractiveViewer(child: Image.memory(base64Decode(preview), fit: BoxFit.contain)))),
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(14),
                              child: preview == null
                                  ? Container(width: 150, height: 120, color: const Color(0xFF0A151D), child: const Icon(Icons.image_outlined))
                                  : Stack(children: [
                                      Image.memory(base64Decode(preview), width: 150, height: 120, fit: BoxFit.cover),
                                      if (!g.scenarioApplied) Positioned(left: 6, bottom: 6, child: Container(padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4), decoration: BoxDecoration(color: Colors.black87, borderRadius: BorderRadius.circular(8)), child: const Text('original', style: TextStyle(fontSize: 11)))),
                                    ]),
                            ),
                          );
                        }),
                        const SizedBox(width: 16),
                        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [Expanded(child: Text(g.title, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800))), if (g.scenarioApplied) const Chip(avatar: Icon(Icons.auto_awesome, size: 16), label: Text('escenario listo'))]),
                          Text('${g.brand} • ${g.model} • ${g.color}', style: const TextStyle(color: muted)),
                          Text('${g.count} vistas conservadas • grupo ${(g.confidence*100).toStringAsFixed(0)}% • marca ${(g.brandConfidence*100).toStringAsFixed(0)}% • modelo ${(g.modelConfidence*100).toStringAsFixed(0)}%', style: const TextStyle(color: ice)),
                          if (g.webConfigured) Text('web ${(g.webConfidence*100).toStringAsFixed(0)}% • ${g.webVerified ? 'confirmado' : 'sin consenso'}', style: TextStyle(color: g.webVerified ? Colors.greenAccent : Colors.amber)),
                          if (g.verificationNote.isNotEmpty) Text(g.verificationNote, style: const TextStyle(color: muted, fontSize: 12)),
                          if (g.needsReview) const Text('Publicado automáticamente con la mejor identificación local; puedes corregirlo después.', style: TextStyle(color: Colors.amber)),
                        ])),
                        Wrap(spacing: 8, runSpacing: 8, children: [
                          ActionButton(text: 'Corregir nombre', icon: Icons.edit_note, onTap: () => showAiCorrectionDialog(context, widget.store, g)),
                          ActionButton(text: 'Buscar referencia web', icon: Icons.manage_search, onTap: () => html.window.open('https://www.google.com/search?tbm=isch&q=${Uri.encodeComponent('${g.brand} ${g.model} ${g.color} sneaker')}', '_blank')),
                          ActionButton(
                            text: processingGroupIds.contains(g.id) ? 'Procesando...' : 'Procesar y publicar',
                            icon: Icons.auto_awesome,
                            onTap: processingGroupIds.contains(g.id) ? null : () => processOneGroup(g, publishWhenConfirmed: true),
                          ),
                          if (g.approved)
                            const Chip(label: Text('En catálogo ✓'))
                          else
                            PrimaryButton(
                              text: 'Aprobar manualmente',
                              icon: Icons.check,
                              onTap: () => widget.store.approveAiGroup(g),
                            ),
                        ]),
                      ],
                    ),
                  );
                },
              ),
      ),
    ],
  );
}


Future<void> showAiCorrectionDialog(BuildContext context, AppStore store, AiGroup g) async {
  final brand = TextEditingController(text: g.brand == 'Unknown' ? '' : g.brand);
  final model = TextEditingController(text: g.model.contains('Other') ? '' : g.model);
  final color = TextEditingController(text: g.color);
  final title = TextEditingController(text: g.title);
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Corregir identificación'),
      content: SizedBox(
        width: 480,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(controller: brand, decoration: const InputDecoration(labelText: 'Marca correcta')),
            const SizedBox(height: 10),
            TextField(controller: model, decoration: const InputDecoration(labelText: 'Modelo o familia correcta')),
            const SizedBox(height: 10),
            TextField(controller: color, decoration: const InputDecoration(labelText: 'Color principal')),
            const SizedBox(height: 10),
            TextField(controller: title, decoration: const InputDecoration(labelText: 'Título del producto')),
            const SizedBox(height: 12),
            const Text('Tu corrección se usará para crear el producto sin inventar datos.', style: TextStyle(color: muted, fontSize: 12)),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancelar')),
        FilledButton(
          onPressed: () {
            if (brand.text.trim().isEmpty || model.text.trim().isEmpty) return;
            g.brand = brand.text.trim();
            g.model = model.text.trim();
            g.color = color.text.trim();
            g.title = title.text.trim().isEmpty ? '${g.brand} ${g.model} ${g.color}' : title.text.trim();
            g.needsReview = false;
            store.notifyListeners();
            Navigator.pop(dialogContext);
          },
          child: const Text('Guardar corrección'),
        ),
      ],
    ),
  );
}

class StudioPage extends StatefulWidget {
  const StudioPage({super.key, required this.store});
  final AppStore store;

  @override
  State<StudioPage> createState() => _StudioPageState();
}

class _StudioPageState extends State<StudioPage> {
  XFile? sourceFile;
  Uint8List? sourceBytes;
  Uint8List? processedBytes;
  String filename = 'elegance_edit.png';
  String brandTheme = 'Automático';
  bool processing = false;

  Future<void> pick() async {
    final x = await ImagePicker().pickImage(source: ImageSource.gallery, imageQuality: 95);
    if (x == null) return;
    final selected = await x.readAsBytes();
    setState(() { sourceFile = x; sourceBytes = selected; processedBytes = null; filename = x.name; });
  }

  Future<void> process() async {
    if (sourceFile == null) return;
    if (widget.store.openAiKey.trim().isEmpty) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Studio funciona en modo local. La fotografía original se conserva para evitar montajes artificiales.')));
      return;
    }
    setState(() => processing = true);
    try {
      final result = await composeWithBackend(
        sourceFile!,
        brandTheme,
        openAiKey: widget.store.openAiKey,
        openAiImageModel: widget.store.openAiImageModel,
      );
      if (result == null) throw Exception('El compositor no devolvió una imagen.');
      setState(() => processedBytes = result);
      widget.store.log('Escenario elegance generado para $brandTheme', Icons.auto_fix_high);
      widget.store.save();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo generar: $e')));
    } finally {
      if (mounted) setState(() => processing = false);
    }
  }

  void download() {
    final bytes = processedBytes ?? sourceBytes;
    if (bytes == null) return;
    final blob = html.Blob([bytes]);
    final url = html.Url.createObjectUrlFromBlob(blob);
    html.AnchorElement(href: url)..setAttribute('download', 'elegance_$filename')..click();
    html.Url.revokeObjectUrl(url);
  }

  @override
  Widget build(BuildContext context) => Column(
    children: [
      _PageHeader(title: 'Studio', subtitle: 'Edición generativa: reconstruye producto, mano, luz y boutique en una sola fotografía.', store: widget.store),
      const SizedBox(height: 18),
      Expanded(
        child: Row(
          children: [
            Expanded(
              flex: 7,
              child: GlassPanel(
                child: sourceBytes == null
                    ? const EmptyState(icon: Icons.auto_fix_high, title: 'Selecciona una fotografía', text: 'El motor visual separará el producto y la mano, eliminará etiquetas y adaptará iluminación, escala y sombra al escenario elegido.')
                    : Column(
                        children: [
                          Expanded(
                            child: Row(
                              children: [
                                Expanded(child: _ImageCompare(title: 'Original', bytes: sourceBytes!)),
                                const SizedBox(width: 12),
                                Expanded(child: processedBytes == null ? const Center(child: Text('Pulsa Generar escenario', style: TextStyle(color: muted))) : _ImageCompare(title: 'Resultado integrado', bytes: processedBytes!)),
                              ],
                            ),
                          ),
                          if (processing) const LinearProgressIndicator(),
                        ],
                      ),
              ),
            ),
            const SizedBox(width: 16),
            SizedBox(
              width: 340,
              child: GlassPanel(
                child: ListView(
                  children: [
                    PrimaryButton(text: 'Seleccionar imagen', icon: Icons.add_photo_alternate_outlined, onTap: processing ? null : pick),
                    const SizedBox(height: 14),
                    DropdownButtonFormField<String>(
                      value: brandTheme,
                      decoration: const InputDecoration(labelText: 'Adaptación de marca/modelo'),
                      items: const ['Automático','Nike','Jordan','Adidas / Yeezy','New Balance','On','Balenciaga','Dior','Gucci','Hugo Boss','Botas / Timberland'].map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                      onChanged: processing ? null : (v) => setState(() => brandTheme = v ?? 'Automático'),
                    ),
                    const SizedBox(height: 14),
                    PrimaryButton(text: processing ? 'Generando...' : 'Generar escenario integrado', icon: Icons.auto_awesome, onTap: processing || sourceFile == null ? null : process),
                    const SizedBox(height: 10),
                    ActionButton(text: 'Exportar resultado', icon: Icons.download, onTap: processedBytes == null ? null : download),
                    const SizedBox(height: 18),
                    Text(widget.store.openAiKey.isEmpty ? 'OpenAI no está configurado. La generación real está bloqueada para evitar fotomontajes.' : 'Motor generativo activo: reconstruye el contacto entre mano y producto y crea una fotografía completa, no un fotomontaje.', style: TextStyle(color: muted, fontSize: 12, height: 1.5)),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    ],
  );
}

class _ImageCompare extends StatelessWidget {
  const _ImageCompare({required this.title, required this.bytes});
  final String title;
  final Uint8List bytes;
  @override Widget build(BuildContext context) => Column(children: [Text(title, style: const TextStyle(fontWeight: FontWeight.w800)), const SizedBox(height: 8), Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(16), child: InteractiveViewer(minScale: .6, maxScale: 4, child: Image.memory(bytes, fit: BoxFit.contain))))]);
}

List<double> colorMatrix(double b, double c, double s) {
  final t = (1 - c) / 2 * 255 + b * 255;
  final inv = 1 - s;
  final r = .213 * inv;
  final g = .715 * inv;
  final bl = .072 * inv;
  return [
    c * (r + s), c * g, c * bl, 0, t,
    c * r, c * (g + s), c * bl, 0, t,
    c * r, c * g, c * (bl + s), 0, t,
    0, 0, 0, 1, 0,
  ];
}

class SliderLabel extends StatelessWidget {
  const SliderLabel({
    super.key,
    required this.text,
    required this.value,
    required this.min,
    required this.max,
    required this.onChanged,
  });
  final String text;
  final double value;
  final double min;
  final double max;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(text),
            const Spacer(),
            Text(value.toStringAsFixed(2), style: const TextStyle(color: ice)),
          ],
        ),
        Slider(value: value, min: min, max: max, onChanged: onChanged),
      ],
    );
  }
}

class InventoryPage extends StatelessWidget {
  const InventoryPage({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _PageHeader(
          title: 'Inventario',
          subtitle: 'Entradas, salidas, existencias y alertas.',
          store: store,
        ),
        const SizedBox(height: 18),
        Expanded(
          child: Row(
            children: [
              Expanded(
                flex: 7,
                child: GlassPanel(
                  child: store.products.isEmpty
                      ? const EmptyState(
                          icon: Icons.inventory_2_outlined,
                          title: 'Sin productos',
                          text: 'Agrega productos en Catálogo.',
                        )
                      : ListView.separated(
                          itemCount: store.products.length,
                          separatorBuilder: (_, __) => const Divider(color: line),
                          itemBuilder: (context, i) {
                            final p = store.products[i];
                            return ListTile(
                              contentPadding: const EdgeInsets.symmetric(
                                vertical: 5,
                                horizontal: 4,
                              ),
                              leading: CircleAvatar(
                                backgroundColor: p.stock < 2
                                    ? Colors.red.withOpacity(.2)
                                    : ice.withOpacity(.15),
                                child: Icon(
                                  Icons.inventory_2_outlined,
                                  color: p.stock < 2 ? Colors.redAccent : ice,
                                ),
                              ),
                              title: Text(
                                p.title,
                                style: const TextStyle(fontWeight: FontWeight.w700),
                              ),
                              subtitle: Text(
                                '${p.sku} • Tallas '
                                '${p.sizes.isEmpty ? 'sin definir' : p.sizes}',
                                style: const TextStyle(color: muted),
                              ),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(
                                    '${p.stock}',
                                    style: const TextStyle(
                                      color: ice,
                                      fontSize: 22,
                                      fontWeight: FontWeight.w900,
                                    ),
                                  ),
                                  IconButton(
                                    onPressed: () => showStockDialog(context, store, p),
                                    icon: const Icon(Icons.swap_vert, color: ice),
                                  ),
                                ],
                              ),
                            );
                          },
                        ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                flex: 4,
                child: GlassPanel(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Movimientos recientes',
                        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 10),
                      Expanded(
                        child: store.movements.isEmpty
                            ? const Center(
                                child: Text('Sin movimientos', style: TextStyle(color: muted)),
                              )
                            : ListView.builder(
                                itemCount: store.movements.take(30).length,
                                itemBuilder: (context, i) {
                                  final m = store.movements[i];
                                  return ListTile(
                                    dense: true,
                                    leading: Icon(
                                      m.delta >= 0
                                          ? Icons.arrow_downward
                                          : Icons.arrow_upward,
                                      color: m.delta >= 0
                                          ? Colors.greenAccent
                                          : Colors.orangeAccent,
                                    ),
                                    title: Text(
                                      m.productTitle,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                    subtitle: Text(
                                      m.reason,
                                      style: const TextStyle(color: muted),
                                    ),
                                    trailing: Text(
                                      '${m.delta >= 0 ? '+' : ''}${m.delta}',
                                      style: const TextStyle(fontWeight: FontWeight.w800),
                                    ),
                                  );
                                },
                              ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

Future<void> showStockDialog(
  BuildContext context,
  AppStore store,
  Product product,
) async {
  final amount = TextEditingController(text: '1');
  final reason = TextEditingController(text: 'Ajuste manual');
  int sign = 1;
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return StatefulBuilder(
        builder: (context, setLocal) {
          return AlertDialog(
            title: Text('Movimiento: ${product.title}'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<int>(
                  value: sign,
                  items: const [
                    DropdownMenuItem(value: 1, child: Text('Entrada')),
                    DropdownMenuItem(value: -1, child: Text('Salida')),
                  ],
                  onChanged: (v) => setLocal(() => sign = v ?? 1),
                  decoration: const InputDecoration(labelText: 'Tipo'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: amount,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Cantidad'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: reason,
                  decoration: const InputDecoration(labelText: 'Motivo'),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('Cancelar'),
              ),
              FilledButton(
                onPressed: () {
                  store.adjustStock(
                    product,
                    sign * (int.tryParse(amount.text) ?? 0),
                    reason.text,
                  );
                  Navigator.pop(dialogContext);
                },
                child: const Text('Guardar'),
              ),
            ],
          );
        },
      );
    },
  );
}

class CustomersPage extends StatelessWidget {
  const CustomersPage({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _PageHeader(
          title: 'Clientes',
          subtitle: 'Contactos, direcciones, notas e historial.',
          store: store,
        ),
        const SizedBox(height: 18),
        Align(
          alignment: Alignment.centerRight,
          child: PrimaryButton(
            text: 'Nuevo cliente',
            icon: Icons.person_add_alt_1,
            onTap: () => showCustomerDialog(context, store),
          ),
        ),
        const SizedBox(height: 14),
        Expanded(
          child: store.customers.isEmpty
              ? const EmptyState(
                  icon: Icons.groups_outlined,
                  title: 'Sin clientes',
                  text: 'Registra tu primer cliente para crear pedidos.',
                )
              : GlassPanel(
                  child: ListView.separated(
                    itemCount: store.customers.length,
                    separatorBuilder: (_, __) => const Divider(color: line),
                    itemBuilder: (context, i) {
                      final customer = store.customers[i];
                      final count = store.orders
                          .where((o) => o.customerId == customer.id)
                          .length;
                      return ListTile(
                        leading: CircleAvatar(
                          backgroundColor: ice.withOpacity(.14),
                          child: Text(
                            customer.name.isEmpty
                                ? '?'
                                : customer.name[0].toUpperCase(),
                            style: const TextStyle(
                              color: ice,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ),
                        title: Text(
                          customer.name,
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                        subtitle: Text(
                          '${customer.phone} • $count pedidos\n${customer.address}',
                          style: const TextStyle(color: muted),
                        ),
                        isThreeLine: true,
                        trailing: IconButton(
                          icon: const Icon(Icons.chat_outlined, color: ice),
                          onPressed: customer.phone.isEmpty
                              ? null
                              : () => html.window.open(
                                    'https://wa.me/52${customer.phone.replaceAll(RegExp(r'\D'), '')}',
                                    '_blank',
                                  ),
                        ),
                      );
                    },
                  ),
                ),
        ),
      ],
    );
  }
}

Future<void> showCustomerDialog(BuildContext context, AppStore store) async {
  final name = TextEditingController();
  final phone = TextEditingController();
  final address = TextEditingController();
  final notes = TextEditingController();
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return AlertDialog(
        title: const Text('Nuevo cliente'),
        content: SizedBox(
          width: 520,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: name, decoration: const InputDecoration(labelText: 'Nombre')),
              const SizedBox(height: 12),
              TextField(controller: phone, decoration: const InputDecoration(labelText: 'WhatsApp')),
              const SizedBox(height: 12),
              TextField(controller: address, decoration: const InputDecoration(labelText: 'Dirección')),
              const SizedBox(height: 12),
              TextField(controller: notes, decoration: const InputDecoration(labelText: 'Notas')),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () {
              if (name.text.trim().isNotEmpty) {
                store.addCustomer(
                  Customer(
                    id: uid(),
                    name: name.text.trim(),
                    phone: phone.text.trim(),
                    address: address.text.trim(),
                    notes: notes.text.trim(),
                  ),
                );
              }
              Navigator.pop(dialogContext);
            },
            child: const Text('Guardar'),
          ),
        ],
      );
    },
  );
}

class OrdersPage extends StatelessWidget {
  const OrdersPage({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) {
    final canCreate = store.products.isNotEmpty && store.customers.isNotEmpty;
    return Column(
      children: [
        _PageHeader(
          title: 'Pedidos',
          subtitle: 'Apartados, anticipos, saldos y seguimiento.',
          store: store,
        ),
        const SizedBox(height: 18),
        Align(
          alignment: Alignment.centerRight,
          child: PrimaryButton(
            text: 'Crear pedido',
            icon: Icons.add_shopping_cart,
            onTap: canCreate ? () => showOrderDialog(context, store) : null,
          ),
        ),
        if (!canCreate)
          Padding(
            padding: const EdgeInsets.all(10),
            child: Text(
              'Necesitas al menos un producto y un cliente para crear pedidos.',
              style: TextStyle(color: Colors.orange.shade200),
            ),
          ),
        const SizedBox(height: 12),
        Expanded(
          child: store.orders.isEmpty
              ? const EmptyState(
                  icon: Icons.shopping_bag_outlined,
                  title: 'Sin pedidos',
                  text: 'Los pedidos aparecerán aquí con su saldo y estado.',
                )
              : ListView.separated(
                  itemCount: store.orders.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (context, i) {
                    final order = store.orders.reversed.toList()[i];
                    return GlassPanel(
                      child: Row(
                        children: [
                          Container(
                            width: 48,
                            height: 48,
                            decoration: BoxDecoration(
                              color: ice.withOpacity(.14),
                              borderRadius: BorderRadius.circular(14),
                            ),
                            child: const Icon(Icons.receipt_long_outlined, color: ice),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${order.folio} • ${order.customerName}',
                                  style: const TextStyle(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                Text(
                                  '${order.lines.length} productos • '
                                  'Total ${money(order.total)} • '
                                  'Saldo ${money(order.balance)}',
                                  style: const TextStyle(color: muted),
                                ),
                              ],
                            ),
                          ),
                          DropdownButton<String>(
                            value: order.status,
                            items: const [
                              'Pendiente',
                              'Apartado',
                              'Pagado',
                              'Enviado',
                              'Entregado',
                              'Cancelado',
                            ].map((x) => DropdownMenuItem(value: x, child: Text(x))).toList(),
                            onChanged: (v) {
                              if (v != null) store.updateOrderStatus(order, v);
                            },
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

Future<void> showOrderDialog(BuildContext context, AppStore store) async {
  Customer customer = store.customers.first;
  final Map<String, int> qty = {};
  final deposit = TextEditingController(text: '0');
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return StatefulBuilder(
        builder: (context, setLocal) {
          return AlertDialog(
            title: const Text('Nuevo pedido'),
            content: SizedBox(
              width: 720,
              height: 520,
              child: Column(
                children: [
                  DropdownButtonFormField<Customer>(
                    value: customer,
                    items: store.customers
                        .map((x) => DropdownMenuItem(value: x, child: Text(x.name)))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) setLocal(() => customer = v);
                    },
                    decoration: const InputDecoration(labelText: 'Cliente'),
                  ),
                  const SizedBox(height: 12),
                  Expanded(
                    child: ListView.separated(
                      itemCount: store.products.length,
                      separatorBuilder: (_, __) => const Divider(color: line),
                      itemBuilder: (context, i) {
                        final product = store.products[i];
                        final n = qty[product.id] ?? 0;
                        return ListTile(
                          title: Text(product.title),
                          subtitle: Text(
                            '${money(product.price)} • Stock ${product.stock}',
                            style: const TextStyle(color: muted),
                          ),
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                onPressed: n > 0
                                    ? () => setLocal(() => qty[product.id] = n - 1)
                                    : null,
                                icon: const Icon(Icons.remove_circle_outline),
                              ),
                              Text(
                                '$n',
                                style: const TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                              IconButton(
                                onPressed: n < product.stock
                                    ? () => setLocal(() => qty[product.id] = n + 1)
                                    : null,
                                icon: const Icon(Icons.add_circle_outline, color: ice),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                  ),
                  TextField(
                    controller: deposit,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Anticipo'),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('Cancelar'),
              ),
              FilledButton(
                onPressed: () {
                  final lines = store.products
                      .where((p) => (qty[p.id] ?? 0) > 0)
                      .map(
                        (p) => OrderLine(
                          productId: p.id,
                          title: p.title,
                          quantity: qty[p.id]!,
                          unitPrice: p.price,
                        ),
                      )
                      .toList();
                  if (lines.isNotEmpty) {
                    store.addOrder(
                      OrderModel(
                        id: uid(),
                        folio: 'PED-${(store.orders.length + 1).toString().padLeft(4, '0')}',
                        customerId: customer.id,
                        customerName: customer.name,
                        lines: lines,
                        deposit: double.tryParse(deposit.text) ?? 0,
                        status: 'Pendiente',
                        createdAt: DateTime.now(),
                      ),
                    );
                  }
                  Navigator.pop(dialogContext);
                },
                child: const Text('Crear pedido'),
              ),
            ],
          );
        },
      );
    },
  );
}

class PublicationsPage extends StatelessWidget {
  const PublicationsPage({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _PageHeader(
          title: 'Publicaciones',
          subtitle: 'Textos de venta y cola para redes sociales.',
          store: store,
        ),
        const SizedBox(height: 18),
        Align(
          alignment: Alignment.centerRight,
          child: PrimaryButton(
            text: 'Preparar publicación',
            icon: Icons.campaign_outlined,
            onTap: store.products.isEmpty
                ? null
                : () => showPublicationDialog(context, store),
          ),
        ),
        const SizedBox(height: 14),
        Expanded(
          child: store.publications.isEmpty
              ? const EmptyState(
                  icon: Icons.campaign_outlined,
                  title: 'Sin publicaciones',
                  text: 'Selecciona un producto y genera su texto comercial.',
                )
              : ListView.separated(
                  itemCount: store.publications.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (context, i) {
                    final publication = store.publications.reversed.toList()[i];
                    return GlassPanel(
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          ClipRRect(
                            borderRadius: BorderRadius.circular(13),
                            child: publication.imageBase64 == null
                                ? Container(
                                    width: 120,
                                    height: 90,
                                    color: ice.withOpacity(.14),
                                    child: const Icon(Icons.campaign_outlined, color: ice),
                                  )
                                : Image.memory(
                                    base64Decode(publication.imageBase64!),
                                    width: 120,
                                    height: 90,
                                    fit: BoxFit.cover,
                                  ),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${publication.productTitle} • ${publication.channel}',
                                  style: const TextStyle(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                const SizedBox(height: 8),
                                SelectableText(
                                  publication.copy,
                                  style: const TextStyle(
                                    color: Color(0xFFCAD8DE),
                                    height: 1.4,
                                  ),
                                ),
                                const SizedBox(height: 12),
                                Wrap(
                                  spacing: 8,
                                  runSpacing: 8,
                                  children: [
                                    ActionButton(
                                      text: 'WhatsApp',
                                      icon: Icons.chat_outlined,
                                      onTap: () => html.window.open('https://wa.me/?text=${Uri.encodeComponent(publication.copy)}', '_blank'),
                                    ),
                                    ActionButton(
                                      text: 'Facebook',
                                      icon: Icons.facebook,
                                      onTap: () => html.window.open('https://www.facebook.com/', '_blank'),
                                    ),
                                    ActionButton(
                                      text: 'Instagram',
                                      icon: Icons.camera_alt_outlined,
                                      onTap: () => html.window.open('https://www.instagram.com/', '_blank'),
                                    ),
                                    ActionButton(
                                      text: 'Descargar fotos',
                                      icon: Icons.download_outlined,
                                      onTap: publication.imagesBase64.isEmpty ? null : () {
                                        for (var j = 0; j < publication.imagesBase64.length; j++) {
                                          final bytes = base64Decode(publication.imagesBase64[j]);
                                          final blob = html.Blob([bytes], 'image/jpeg');
                                          final url = html.Url.createObjectUrlFromBlob(blob);
                                          html.AnchorElement(href: url)
                                            ..setAttribute('download', '${publication.productTitle.replaceAll(RegExp(r'[^a-zA-Z0-9]+'), '_')}_${j + 1}.jpg')
                                            ..click();
                                          html.Url.revokeObjectUrl(url);
                                        }
                                      },
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                          Column(
                            children: [
                              IconButton(
                                tooltip: 'Elegir mejores fotos',
                                onPressed: () => showPublicationPhotosDialog(context, store, publication),
                                icon: const Icon(Icons.photo_library_outlined, color: ice),
                              ),
                              IconButton(
                                tooltip: 'Copiar texto',
                                onPressed: () {
                                  html.window.navigator.clipboard?.writeText(publication.copy);
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    const SnackBar(content: Text('Texto copiado')),
                                  );
                                },
                                icon: const Icon(Icons.copy, color: ice),
                              ),
                            ],
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

Future<void> showPublicationPhotosDialog(BuildContext context, AppStore store, Publication publication) async {
  final product = store.products.where((p) => p.id == publication.productId).firstOrNull;
  final available = <String>[
    ...publication.imagesBase64,
    if (product?.imageBase64 != null) product!.imageBase64!,
    ...?product?.galleryBase64,
  ].where((e) => e.isNotEmpty).toSet().toList();
  final selected = <String>{...publication.imagesBase64};
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => StatefulBuilder(
      builder: (context, setLocal) => AlertDialog(
        title: const Text('Elegir las mejores fotos'),
        content: SizedBox(
          width: 850,
          height: 560,
          child: available.isEmpty
              ? const EmptyState(icon: Icons.photo_library_outlined, title: 'Sin fotos', text: 'Este producto no tiene imágenes disponibles.')
              : GridView.builder(
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 3, crossAxisSpacing: 12, mainAxisSpacing: 12, childAspectRatio: .85),
                  itemCount: available.length,
                  itemBuilder: (_, i) {
                    final image = available[i];
                    final checked = selected.contains(image);
                    return InkWell(
                      onTap: () => setLocal(() => checked ? selected.remove(image) : selected.add(image)),
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          ClipRRect(borderRadius: BorderRadius.circular(14), child: Image.memory(base64Decode(image), fit: BoxFit.cover)),
                          Positioned(top: 8, right: 8, child: CircleAvatar(backgroundColor: checked ? ice : Colors.black87, child: Icon(checked ? Icons.check : Icons.add, color: checked ? Colors.black : Colors.white))),
                          if (i == 0) Positioned(left: 8, bottom: 8, child: Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4), decoration: BoxDecoration(color: Colors.black87, borderRadius: BorderRadius.circular(8)), child: const Text('imagen final'))),
                        ],
                      ),
                    );
                  },
                ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancelar')),
          FilledButton(
            onPressed: selected.isEmpty ? null : () {
              publication.imagesBase64 = selected.toList();
              publication.imageBase64 = publication.imagesBase64.first;
              publication.status = 'Fotos seleccionadas';
              store.updatePublication(publication);
              Navigator.pop(dialogContext);
            },
            child: Text('Guardar ${selected.length} fotos'),
          ),
        ],
      ),
    ),
  );
}

Future<void> showPublicationDialog(BuildContext context, AppStore store) async {
  Product product = store.products.first;
  String channel = 'WhatsApp';
  final copy = TextEditingController();

  void generate() {
    copy.text = '✨ ${product.title}\n\n'
        '${product.brand} ${product.model} en color ${product.color}.\n'
        'Tallas: ${product.sizes.isEmpty ? 'pregunta disponibilidad' : product.sizes}\n'
        'Precio: ${money(product.price)}\n\n'
        '📦 Stock disponible: ${product.stock}\n'
        '📲 Aparta por mensaje.\n\n'
        '#elegance #sneakers #${product.brand.replaceAll(' ', '')}';
  }

  generate();
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return StatefulBuilder(
        builder: (context, setLocal) {
          return AlertDialog(
            title: const Text('Preparar publicación'),
            content: SizedBox(
              width: 650,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (product.imageBase64 != null) ...[
                    ClipRRect(
                      borderRadius: BorderRadius.circular(16),
                      child: Image.memory(base64Decode(product.imageBase64!), height: 210, width: double.infinity, fit: BoxFit.cover),
                    ),
                    const SizedBox(height: 12),
                    const Text('Esta es la imagen final editada que se publicará.', style: TextStyle(color: muted, fontSize: 12)),
                    const SizedBox(height: 12),
                  ],
                  DropdownButtonFormField<Product>(
                    value: product,
                    items: store.products
                        .map((x) => DropdownMenuItem(value: x, child: Text(x.title)))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) {
                        setLocal(() => product = v);
                        generate();
                      }
                    },
                    decoration: const InputDecoration(labelText: 'Producto'),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    value: channel,
                    items: const ['WhatsApp', 'Facebook', 'Instagram', 'Marketplace']
                        .map((x) => DropdownMenuItem(value: x, child: Text(x)))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) setLocal(() => channel = v);
                    },
                    decoration: const InputDecoration(labelText: 'Canal'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: copy,
                    maxLines: 10,
                    decoration: const InputDecoration(labelText: 'Texto'),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('Cancelar'),
              ),
              FilledButton(
                onPressed: () {
                  store.addPublication(
                    Publication(
                      id: uid(),
                      productId: product.id,
                      productTitle: product.title,
                      channel: channel,
                      copy: copy.text,
                      status: 'Lista',
                      createdAt: DateTime.now(),
                      imageBase64: product.imageBase64,
                      imagesBase64: <String>[if (product.imageBase64 != null) product.imageBase64!, ...product.galleryBase64].toSet().toList(),
                    ),
                  );
                  Navigator.pop(dialogContext);
                },
                child: const Text('Guardar'),
              ),
            ],
          );
        },
      );
    },
  );
}

class StatisticsPage extends StatelessWidget {
  const StatisticsPage({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) {
    final byBrand = <String, int>{};
    for (final p in store.products) {
      byBrand[p.brand] = (byBrand[p.brand] ?? 0) + p.stock;
    }
    final sorted = byBrand.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final ticket = store.orders.isEmpty ? 0 : store.totalSales / store.orders.length;
    return ListView(
      children: [
        _PageHeader(
          title: 'Estadísticas',
          subtitle: 'Indicadores alimentados por los datos guardados.',
          store: store,
        ),
        const SizedBox(height: 18),
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth > 900 ? 4 : 2;
            return GridView.count(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: columns,
              crossAxisSpacing: 14,
              mainAxisSpacing: 14,
              childAspectRatio: 2.1,
              children: [
                MetricCard(
                  label: 'Ventas',
                  value: money(store.totalSales),
                  note: 'pedidos no cancelados',
                  icon: Icons.payments_outlined,
                ),
                MetricCard(
                  label: 'Inventario',
                  value: '${store.totalStock}',
                  note: 'piezas disponibles',
                  icon: Icons.inventory_2_outlined,
                ),
                MetricCard(
                  label: 'Clientes',
                  value: '${store.customers.length}',
                  note: 'registrados',
                  icon: Icons.groups_outlined,
                ),
                MetricCard(
                  label: 'Ticket promedio',
                  value: money(ticket),
                  note: 'por pedido',
                  icon: Icons.receipt_long_outlined,
                ),
              ],
            );
          },
        ),
        const SizedBox(height: 18),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: GlassPanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Inventario por marca',
                      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 16),
                    if (sorted.isEmpty)
                      const Text('Sin datos', style: TextStyle(color: muted))
                    else
                      ...sorted.take(8).map(
                            (e) => BrandBar(
                              label: e.key.isEmpty ? 'Sin marca' : e.key,
                              value: e.value,
                              max: sorted.first.value,
                            ),
                          ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: GlassPanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Resumen comercial',
                      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 16),
                    InfoLine(
                      label: 'Pedidos entregados',
                      value: '${store.orders.where((x) => x.status == 'Entregado').length}',
                    ),
                    InfoLine(label: 'Pedidos pendientes', value: '${store.activeOrders}'),
                    InfoLine(
                      label: 'Publicaciones listas',
                      value: '${store.publications.length}',
                    ),
                    InfoLine(
                      label: 'Movimientos de inventario',
                      value: '${store.movements.length}',
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class BrandBar extends StatelessWidget {
  const BrandBar({super.key, required this.label, required this.value, required this.max});
  final String label;
  final int value;
  final int max;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 13),
      child: Column(
        children: [
          Row(
            children: [
              Text(label),
              const Spacer(),
              Text('$value', style: const TextStyle(color: ice, fontWeight: FontWeight.w800)),
            ],
          ),
          const SizedBox(height: 6),
          LinearProgressIndicator(
            value: max == 0 ? 0 : value / max,
            minHeight: 7,
            borderRadius: BorderRadius.circular(10),
            backgroundColor: Colors.white10,
            color: ice,
          ),
        ],
      ),
    );
  }
}

class InfoLine extends StatelessWidget {
  const InfoLine({super.key, required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: line)),
      ),
      child: Row(
        children: [
          Text(label, style: const TextStyle(color: muted)),
          const Spacer(),
          Text(
            value,
            style: const TextStyle(
              color: ice,
              fontSize: 18,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class SettingsPage extends StatelessWidget {
  const SettingsPage({
    super.key,
    required this.store,
    required this.onCheck,
  });
  final AppStore store;
  final VoidCallback onCheck;

  @override
  Widget build(BuildContext context) {
    return ListView(
      children: [
        _PageHeader(
          title: 'Configuración',
          subtitle: 'Sistema local gratuito, respaldo y reglas de identificación.',
          store: store,
        ),
        const SizedBox(height: 18),
        GlassPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Servidor local',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 10),
              const InfoLine(label: 'Dirección', value: '127.0.0.1:8000'),
              InfoLine(
                label: 'Estado',
                value: store.backendOnline ? 'Activo' : 'Sin conexión',
              ),
              const SizedBox(height: 14),
              PrimaryButton(
                text: 'Comprobar servidor',
                icon: Icons.refresh,
                onTap: onCheck,
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        GlassPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Identificación local gratuita', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              Text(
                'Activa. Elegance detecta primero la marca por evidencia local y solo completa el modelo cuando la confianza es suficiente. Si duda, deja el modelo vacío.',
                style: const TextStyle(color: muted, height: 1.4),
              ),
              const SizedBox(height: 14),
              ActionButton(
                text: 'Probar identificación local',
                icon: Icons.manage_search,
                onTap: () async {
                  final controller = TextEditingController(text: store.googleVisionKey);
                  await showDialog<void>(
                    context: context,
                    builder: (dialogContext) => AlertDialog(
                      title: const Text('Google Vision opcional'),
                      content: SizedBox(
                        width: 560,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            TextField(
                              controller: controller,
                              obscureText: true,
                              decoration: const InputDecoration(labelText: 'Google Vision API key'),
                            ),
                            const SizedBox(height: 12),
                            const Text('OpenAI ya realiza la identificación principal con búsqueda web. Esta clave solo se usa como respaldo opcional. Se guarda únicamente en este navegador y se envía al backend local durante el análisis.', style: TextStyle(color: muted, fontSize: 12, height: 1.4)),
                          ],
                        ),
                      ),
                      actions: [
                        TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancelar')),
                        FilledButton(
                          onPressed: () {
                            store.googleVisionKey = controller.text.trim();
                            store.save();
                            Navigator.pop(dialogContext);
                          },
                          child: const Text('Guardar'),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        GlassPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Studio local (opcional)', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              Text(
                'Auto Sync ya no depende de Studio. El catálogo publica la fotografía original optimizada; Studio queda como herramienta opcional local.',
                style: const TextStyle(color: muted, height: 1.4),
              ),
              const SizedBox(height: 14),
              ActionButton(
                text: 'Sin APIs de pago',
                icon: Icons.auto_awesome,
                onTap: () async {
                  final controller = TextEditingController(text: store.openAiKey);
                  String selectedModel = AppStore.supportedImageModels.contains(store.openAiImageModel)
                      ? store.openAiImageModel
                      : AppStore.supportedImageModels.first;
                  await showDialog<void>(
                    context: context,
                    builder: (dialogContext) => StatefulBuilder(
                      builder: (context, setDialogState) => AlertDialog(
                        title: const Text('Motor generativo de imágenes'),
                        content: SizedBox(
                          width: 560,
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              TextField(controller: controller, obscureText: true, decoration: const InputDecoration(labelText: 'OpenAI API key')),
                              const SizedBox(height: 12),
                              DropdownButtonFormField<String>(
                                value: selectedModel,
                                decoration: const InputDecoration(labelText: 'Modelo de imagen'),
                                items: AppStore.supportedImageModels
                                    .map((e) => DropdownMenuItem<String>(value: e, child: Text(e)))
                                    .toList(),
                                onChanged: (v) => setDialogState(() => selectedModel = v ?? 'gpt-image-1'),
                              ),
                              const SizedBox(height: 12),
                              Text('Identificación web: ${store.openAiTextModel}', style: const TextStyle(color: muted)),
                              const SizedBox(height: 12),
                              const Text('La clave se guarda únicamente en este navegador y se envía a tu backend local para cada generación.', style: TextStyle(color: muted, fontSize: 12, height: 1.4)),
                            ],
                          ),
                        ),
                        actions: [
                          TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancelar')),
                          FilledButton(onPressed: () { store.openAiKey = controller.text.trim(); store.openAiImageModel = selectedModel; store.save(); Navigator.pop(dialogContext); }, child: const Text('Guardar')),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        GlassPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Datos de elegance',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 8),
              const Text(
                'El catálogo, clientes, pedidos e inventario se guardan '
                'en el almacenamiento local del navegador.',
                style: TextStyle(color: muted),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  ActionButton(
                    text: 'Exportar respaldo JSON',
                    icon: Icons.download,
                    onTap: () {
                      final raw = html.window.localStorage[AppStore.key] ?? '{}';
                      final blob = html.Blob([raw]);
                      final url = html.Url.createObjectUrlFromBlob(blob);
                      html.AnchorElement(href: url)
                        ..setAttribute('download', 'elegance_respaldo.json')
                        ..click();
                      html.Url.revokeObjectUrl(url);
                    },
                  ),
                  ActionButton(
                    text: 'Borrar todos los datos',
                    icon: Icons.delete_forever_outlined,
                    onTap: () => showDialog<void>(
                      context: context,
                      builder: (dialogContext) => AlertDialog(
                        title: const Text('Borrar todos los datos'),
                        content: const Text(
                          'Esta acción elimina catálogo, clientes, pedidos '
                          'e inventario guardados en este navegador.',
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(dialogContext),
                            child: const Text('Cancelar'),
                          ),
                          FilledButton(
                            onPressed: () {
                              html.window.localStorage.remove(AppStore.key);
                              html.window.location.reload();
                            },
                            child: const Text('Borrar'),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class GlassPanel extends StatelessWidget {
  const GlassPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(20),
  });
  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: panel,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: line),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(.28),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: child,
    );
  }
}

class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    required this.note,
    required this.icon,
  });
  final String label;
  final String value;
  final String note;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: ice.withOpacity(.12),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: line),
            ),
            child: Icon(icon, color: ice),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(label, style: const TextStyle(color: muted)),
                Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: ice,
                    fontSize: 25,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                Text(
                  note,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Color(0xFF6F8793),
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    super.key,
    required this.text,
    required this.icon,
    required this.onTap,
  });
  final String text;
  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return FilledButton.icon(
      onPressed: onTap,
      icon: Icon(icon, size: 18),
      label: Text(text),
      style: FilledButton.styleFrom(
        backgroundColor: ice,
        foregroundColor: const Color(0xFF03202C),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        textStyle: const TextStyle(fontWeight: FontWeight.w800),
      ),
    );
  }
}

class ActionButton extends StatelessWidget {
  const ActionButton({
    super.key,
    required this.text,
    required this.icon,
    required this.onTap,
  });
  final String text;
  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: onTap,
      icon: Icon(icon, size: 18),
      label: Text(text),
      style: OutlinedButton.styleFrom(
        foregroundColor: onTap == null ? muted : const Color(0xFFBFEFFF),
        side: const BorderSide(color: line),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    );
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.text, required this.ok});
  final String text;
  final bool ok;

  @override
  Widget build(BuildContext context) {
    final color = ok ? ice : Colors.orange;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xAA071722),
        borderRadius: BorderRadius.circular(30),
        border: Border.all(color: color.withOpacity(.6)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: color,
              boxShadow: [BoxShadow(color: color.withOpacity(.7), blurRadius: 8)],
            ),
          ),
          const SizedBox(width: 7),
          Text(text, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.text,
  });
  final IconData icon;
  final String title;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: ice, size: 62),
          const SizedBox(height: 14),
          Text(title, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text(text, textAlign: TextAlign.center, style: const TextStyle(color: muted)),
        ],
      ),
    );
  }
}

String money(num n) => '\$${n.toStringAsFixed(2)}';
