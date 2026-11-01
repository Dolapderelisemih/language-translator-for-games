from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

class RegionSelector(QWidget):
    region_selected = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.start_point = QPoint()
        self.end_point = QPoint()
        self.is_selecting = False

        # Çoklu monitör desteği: Tüm ekranların birleşik geometrisini kapla
        total_rect = QRect()
        for s in QApplication.screens():
            total_rect = total_rect.united(s.geometry())
        self.setGeometry(total_rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.pos()
            self.end_point = self.start_point
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_point = event.pos()
            
            rect = QRect(self.start_point, self.end_point).normalized()
            if rect.width() >= 20 and rect.height() >= 15:
                # Global koordinatlara dönüştür
                global_top_left = self.mapToGlobal(rect.topLeft())
                roi = {
                    "left": global_top_left.x(),
                    "top": global_top_left.y(),
                    "width": rect.width(),
                    "height": rect.height()
                }
                self.region_selected.emit(roi)
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Ekranı hafif karart
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        # Bilgi metni
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        info_text = "Diyalog / Altyazı alanını farenizle sürükleyerek seçin (İptal için ESC)"
        painter.drawText(self.rect().center().x() - 250, 70, info_text)

        if self.is_selecting:
            rect = QRect(self.start_point, self.end_point).normalized()
            # Seçili alanın içini şeffaf yap (net görünmesi için)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # Şık neon turkuaz çerçeve çiz
            pen = QPen(QColor(0, 220, 255), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect)
            
            # Boyut bilgisi
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(rect.x() + 5, rect.y() - 8, f"{rect.width()}x{rect.height()} px")
