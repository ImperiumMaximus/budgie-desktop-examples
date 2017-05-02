#!/usr/bin/env python3

# Copyright (C) 2016 Ikey Doherty
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#  
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import gi.repository
gi.require_version('Budgie', '1.0')
gi.require_version('Wnck', '3.0')
from gi.repository import Budgie, GObject, Wnck, Gtk, Gio
import subprocess
import ast
import re


class PyShowDesktop(GObject.GObject, Budgie.Plugin):
    """ This is simply an entry point into your Budgie Applet implementation.
        Note you must always override Object, and implement Plugin.
    """

    # Good manners, make sure we have unique name in GObject type system
    __gtype_name__ = "CpuPower"

    def __init__(self):
        """ Initialisation is important.
        """
        GObject.Object.__init__(self)

    def do_get_panel_widget(self, uuid):
        """ This is where the real fun happens. Return a new Budgie.Applet
            instance with the given UUID. The UUID is determined by the
            BudgiePanelManager, and is used for lifetime tracking.
        """
        return CpuPowerApplet(uuid)

class CpuPowerApplet(Budgie.Applet):
    """ Budgie.Applet is in fact a Gtk.Bin """

    cpupower_proxy = None
    settings = None
    profiles = None

    def __init__(self, uuid):
        Budgie.Applet.__init__(self)

        self.cpupower_proxy = CpuPowerProxy()
        self.settings = Gio.Settings("com.solus-project.budgie-panel.applets.cpupower")
        self.settings.connect_after('changed', self.settings_changed)
        self.profiles_box = Gtk.VBox()

        self.freq = Gtk.Label.new()

        button_box = Gtk.Box()

        # Add a button to our UI
        self.button = Gtk.Button.new()
        self.button.set_relief(Gtk.ReliefStyle.NONE)
        self.add(self.button)

        img = Gtk.Image.new_from_icon_name("cpu-frequency-indicator", Gtk.IconSize.BUTTON)

        button_box.pack_start(self.freq, False, False, 3)
        button_box.pack_start(img, False, False, 0)

        self.button.add(button_box)
        self.show_all()

        self.popover = Gtk.Popover.new(self.button)
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.min_freq_label = Gtk.Label.new()
        self.min_freq_scale = Gtk.HScale.new_with_range(min=0, max=100, step=1)
        self.min_freq_scale.set_draw_value(False)

        self.max_freq_label = Gtk.Label.new()
        self.max_freq_scale = Gtk.HScale.new_with_range(min=0, max=100, step=1)
        self.max_freq_scale.set_draw_value(False)

        self.tb_switch = Gtk.Switch.new()

        self.cur_freq_label = Gtk.Label.new()

        tb_box = Gtk.HBox()
        tb_box.pack_start(Gtk.Label.new("Turbo Boost:"), True, True, 0)
        tb_box.pack_start(self.tb_switch, False, False, 0)

        popover_box.pack_start(self.min_freq_label, True, True, 5)
        popover_box.pack_start(self.min_freq_scale, True, True, 5)
        popover_box.pack_start(Gtk.HSeparator(), False, False, 0)
        popover_box.pack_start(self.max_freq_label, True, True, 5)
        popover_box.pack_start(self.max_freq_scale, True, True, 5)
        popover_box.pack_start(Gtk.HSeparator(), False, False, 0)
        popover_box.pack_start(tb_box, False, False, 5)
        popover_box.pack_start(Gtk.HSeparator(), True, True, 5)
        popover_box.pack_start(self.cur_freq_label, True, True, 5)
        popover_box.pack_start(Gtk.HSeparator(), True, True, 5)
        popover_box.pack_start(self.profiles_box, False, False, 5)
        popover_box.set_property('margin', 10)

        self.popover.add(popover_box)

        popover_box.show_all()

        self.populate_profiles_in_popover()

        self.min_freq_scale.connect_after('value-changed', self.freq_value_changed,
                                          ['Minimum Frequency: %d%%', self.min_freq_label, 0])
        self.max_freq_scale.connect_after('value-changed', self.freq_value_changed,
                                          ['Maximum Frequency: %d%%', self.max_freq_label, 1])

        self.button.connect_after('clicked', self.on_clicked)

        self.update_ui()

        self.tb_switch.connect_after('notify::active', self.on_tb_switch_activated)


        GObject.timeout_add(self.settings.get_int('update-frequency') * 1000, self.update_ui)

    def freq_value_changed(self, widg, data=None):
        data[1].set_label(data[0] % widg.get_value())

        if data[2] == 0:
            self.cpupower_proxy.set_min_perf_pct(widg.get_value())
        elif data[2] == 1:
            self.cpupower_proxy.set_max_perf_pct(widg.get_value())

    def do_update_popovers(self, manager=None):
        self.manager = manager
        manager.register_popover(self.button, self.popover)

    def on_clicked(self, widg, data=None):
        if self.popover.get_visible():
            self.popover.hide()
        else:
            self.manager.show_popover(self.button)

    def on_tb_switch_activated(self, widg, data=None):
        self.cpupower_proxy.set_tb_state(self.tb_switch.get_state())

    def update_ui(self):
        cur_freq = self.cpupower_proxy.get_current_freq()

        if self.settings.get_boolean('panel-freq-unit-ghz') and cur_freq[1] == 'MHz':
            cur_freq[0] = "%.2f" % (float(cur_freq[0]) / 1000.0)
            cur_freq[1] = 'GHz'
        elif not self.settings.get_boolean('panel-freq-unit-ghz') and cur_freq[1] == 'GHz':
            cur_freq[0] = "%.0f" % (float(cur_freq[0]) * 1000.0)
            cur_freq[1] = 'MHz'

        cur_freq = ' '.join(cur_freq)

        self.freq.set_label(cur_freq)
        self.cur_freq_label.set_label("Current Frequency: %s" % cur_freq)

        self.tb_switch.set_state(self.cpupower_proxy.get_tb_state())

        min_pct = self.cpupower_proxy.get_min_perf_pct()
        self.min_freq_scale.set_value(min_pct)

        max_pct = self.cpupower_proxy.get_max_perf_pct()
        self.max_freq_scale.set_value(max_pct)

        return True

    def settings_changed(self, settings, key, data=None):
        if key == 'show-freq-in-panel':
            self.freq.set_visible(self.settings.get_boolean(key))

    def populate_profiles_in_popover(self):
        self.profiles = ast.literal_eval(self.settings.get_string('profiles'))
        last_radio = None
        index = 0
        for child in self.profiles_box.get_children():
            self.profiles_box.remove(child)
        for profile in self.profiles:
            r = Gtk.RadioButton.new_with_mnemonic_from_widget(last_radio, profile[3])
            self.profiles_box.pack_start(r, True, True, 3)
            last_radio = r
            if index == self.settings.get_int('last-profile'):
                r.set_active(True)
            else:
                r.set_active(False)
            r.connect_after('toggled', self.profile_changed, index)
            index += 1

        self.profiles_box.show_all()

    def profile_changed(self, widg, index):
        if widg.get_active():
            min_pct = self.profiles[index][0]
            max_pct = self.profiles[index][1]
            tb_enabled = self.profiles[index][2]

            self.max_freq_scale.set_value(max_pct)
            self.min_freq_scale.set_value(min_pct)
            self.tb_switch.set_state(tb_enabled)
            self.settings.set_int('last-profile', index)



class CpuPowerProxy():

    tb_supported = None

    def get_current_freq(self):
        output = subprocess.check_output(['cpupower', 'frequency-info']).decode('utf-8')
        m = re.search('current CPU frequency: (([0-9]+|[0-9]+\.[0-9]+) (MHz|GHz))', output)
        return m.group(1).split(' ')

    def is_tb_supported(self):
        if self.tb_supported is None:
            output = subprocess.check_output(['cpupower', 'frequency-info']).decode('utf-8')
            m = re.search('boost state support:\\n {4}Supported: (yes|no)', output)
            self.tb_supported = m.group(1) == 'yes'

        return self.tb_supported

    def set_tb_state(self, value):
        if self.is_tb_supported():
            v = "1" if value == False else "0"
            subprocess.call(["/usr/bin/cpufreqctl", "turbo", v])


    def get_tb_state(self):
        if self.is_tb_supported():
            output = subprocess.check_output(["/usr/bin/cpufreqctl", "turbo", "get"]).decode('utf-8').strip()
            return output == "0"

    def get_max_perf_pct(self):
        output = subprocess.check_output(["/usr/bin/cpufreqctl", "max", "get"]).decode('utf-8').strip()

        return int(output)

    def get_min_perf_pct(self):
        output = subprocess.check_output(["/usr/bin/cpufreqctl", "min", "get"]).decode(
            'utf-8').strip()

        return int(output)

    def set_min_perf_pct(self, value):
        subprocess.call(["/usr/bin/cpufreqctl", "min", str(int(value))])

    def set_max_perf_pct(self, value):
        subprocess.call(["/usr/bin/cpufreqctl", "max", str(int(value))])