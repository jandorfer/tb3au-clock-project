import tb3au, time
tb3au._KEEP_AWAKE = True  # mimic the daemon
tb3au.init_display()
tb3au.clear_display(tb3au.epd)
time.sleep(3)
ok1 = tb3au.render_text("RENDER ONE")
print("render1:", ok1)
time.sleep(5)
ok2 = tb3au.render_text("RENDER TWO")
print("render2:", ok2)
time.sleep(5)
print("done")
