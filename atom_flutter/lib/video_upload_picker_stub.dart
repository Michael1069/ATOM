import 'dart:typed_data';

class VideoUploadSelection {
  const VideoUploadSelection({required this.name, required this.bytes});

  final String name;
  final Uint8List bytes;
}

Future<VideoUploadSelection?> pickVideoForUpload() async => null;
