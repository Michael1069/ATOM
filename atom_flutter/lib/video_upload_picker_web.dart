// This file is imported only when dart.library.html is available.
// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter

import 'dart:html' as html;
import 'dart:typed_data';

class VideoUploadSelection {
  const VideoUploadSelection({required this.name, required this.bytes});

  final String name;
  final Uint8List bytes;
}

Future<VideoUploadSelection?> pickVideoForUpload() async {
  final input = html.FileUploadInputElement()
    ..accept = 'video/mp4,.mp4'
    ..multiple = false;
  // Some browsers discard the selected file from a detached input element.
  // Attach it for the lifetime of the picker, then remove it again.
  html.document.body?.append(input);
  try {
    // Subscribe before opening the native chooser: Chromium can dispatch the
    // change event during the nested file-dialog loop.
    final changed = input.onChange.first;
    input.click();
    await changed;
    final file = input.files?.isNotEmpty == true ? input.files!.first : null;
    if (file == null) return null;
    final reader = html.FileReader();
    final loaded = reader.onLoadEnd.first;
    reader.readAsArrayBuffer(file);
    await loaded;
    final result = reader.result;
    final bytes = switch (result) {
      ByteBuffer value => value.asUint8List(),
      Uint8List value => value,
      _ => null,
    };
    if (bytes == null || bytes.isEmpty) return null;
    return VideoUploadSelection(name: file.name, bytes: bytes);
  } finally {
    input.remove();
  }
}
