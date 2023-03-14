import os
import sys
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *

class IconChanger(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Folder Icon Changer')
        self.setGeometry(100, 100, 350, 200)

        folder_label = QLabel('Folder:', self)
        folder_label.move(20, 20)

        self.folder_text = QLineEdit(self)
        self.folder_text.move(80, 20)
        self.folder_text.resize(200, 25)

        folder_button = QPushButton('Select Folder', self)
        folder_button.move(290, 20)
        folder_button.clicked.connect(self.select_folder)

        icon_label = QLabel('Icon:', self)
        icon_label.move(20, 60)

        self.icon_text = QLineEdit(self)
        self.icon_text.move(80, 60)
        self.icon_text.resize(200, 25)

        icon_button = QPushButton('Select Icon', self)
        icon_button.move(290, 60)
        icon_button.clicked.connect(self.select_icon)

        apply_button = QPushButton('Apply Icon', self)
        apply_button.move(20, 100)
        apply_button.clicked.connect(self.apply_icon)

        self.show()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Folder')
        self.folder_text.setText(folder)

    def select_icon(self):
        icon = QFileDialog.getOpenFileName(self, 'Select Icon', '', 'Icon Files (*.ico)')
        self.icon_text.setText(icon[0])

    def apply_icon(self):
        folder_path = self.folder_text.text()
        icon_path = self.icon_text.text()
        if not os.path.exists(folder_path):
            QMessageBox.warning(self, 'Error', 'The selected folder does not exist.')
        elif not os.path.exists(icon_path):
            QMessageBox.warning(self, 'Error', 'The selected icon does not exist.')
        else:
            try:
                with open(icon_path, 'rb') as icon_file:
                    icon_data = icon_file.read()
                if sys.platform == 'win32':
                    # On Windows, use the win32api module to set the folder icon
                    import win32api, win32con
                    win32api.SetFileAttributes(folder_path, win32con.FILE_ATTRIBUTE_NORMAL)
                    win32api.SetFileAttributes(icon_path, win32con.FILE_ATTRIBUTE_NORMAL)
                    win32api.SHChangeNotify(win32con.SHCNE_ASSOCCHANGED, win32con.SHCNF_IDLIST, None, None)
                    win32api.SHSetLocalizedName(folder_path, icon_path)
                else:
                    # On other platforms, set the folder icon using xdg-icon-resource
                    icon_name = os.path.basename(icon_path).replace('.ico', '')
                    os.system(f'xdg-icon-resource install --context emblems --size 64 {icon_path} {icon_name}')
                    os.system(f'gio set "{folder_path}" metadata::emblems {icon_name}')
                QMessageBox.information(self, 'Success', 'The folder icon was successfully changed.')
            except Exception as e:
                QMessageBox.warning(self, 'Error', f'An error occurred: {str(e)}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    icon_changer = IconChanger()
    sys.exit(app.exec())
