#include "keepassxc-browser.hpp"

#include <fstream>
#include <filesystem>
#include <cstdlib>


namespace fs = std::filesystem;


template <typename... Args>
void die(int code, Args... msg) {
    (std::cerr << ... << msg) << std::endl;
    exit(code);
}

int main(int argc, char **argv) {
    if (::sodium_init() < 0)
        die(-44, "Error: Could not initialize libsodium");

    if (argc < 2)
        die(-1, "Usage: ", argv[0], " <url>");

    // Try to make the cli emulate pass at some point
    auto config_path = fs::path{getenv("HOME")} / ".config/keepassxc-pass.json";

    auto conf = [&config_path]() {
        if (!fs::exists(config_path)) {
            auto opt = keepassxc::config::create();
            if (!opt)
                die(-6, "Error: Could not initialize secrets");
            return opt.value();
        } else {
            auto s = std::ifstream(config_path);
            auto v = Json::Value{};
            s >> v;
            auto opt = keepassxc::config::load(v);
            if (!opt)
                die(-5, "Error: Could not load secrets from config");
            return opt.value();
        }
    }();

    auto client = keepassxc::client(conf);

    if (!client.connect())
        die(-2, "Error: Could not popen keepass");
    
    // Hide new association behind a flag?
    auto err = client.associate();
    if (!err.empty())
        die(-3, "Error: Could not associate with keepass: ", err);

    auto s = std::ofstream(config_path);
    s << client.get_config().serialize();
    s.close();
    fs::permissions(config_path, fs::perms::owner_read|fs::perms::owner_write);

    auto res = client.send_get_logins(argv[1]);
    if (res["success"] != "true")
        die(-4, "Error: Could not get logins: ", res["error"].asString());

    if (res["count"] == "0")
        die(1, "No logins found");

    std::cout << res["entries"][0]["password"].asString() << std::endl;
    return 0;
}
