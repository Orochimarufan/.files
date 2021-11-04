// Simple Client-Library for the KeePassXC-Browser API
// (c) 2019 Taeyeon Mori
//
// Depends on: libsodium, jsoncpp
//
// NOTE: Users must make sure to initialize libsodium!
// WARNING: This currently does nothing to protect the keys in memory.
//          Such measures could be added to crypto::, but as the key material
//          is stored in a plain file on disk anyway, that seems to be a lot of useless work.
//          This applies especially for small, short-lived cli utilities.
// WARNING: With a plain secrets file, the 'Never ask before accessing credentials' option in
//          in KeePassXC becomes an even bigger security risk!

#pragma once

#include "koproc.hpp"

#include <json/json.h>
#include <sodium.h>

#include <string>
#include <iostream>
#include <sstream>
#include <optional>
#include <utility>
#include <memory>
#include <cstring>
#include <variant>
#include <unordered_map>

#include <unistd.h>


namespace keepassxc {
    using string = std::string;
    using data = std::basic_string<uint8_t>;
    
    // Hack, but libsodium insists on unsigned char
    // The result of this is cleaner than having individual
    // casts all over the place and as a side benefit, it
    // tends to prevent toughtlessly trying to put binary
    // data into json directly.
    const data &data_cast(const string &s) {
        return *reinterpret_cast<const data*>(&s);
    }
    
    const string &nodata_cast(const data &d) {
        return *reinterpret_cast<const string*>(&d);
    }

    /**
     * Cryptography goes here
     */
    namespace crypto {
        data generate_nonce() {
            auto nonce = data(crypto_box_NONCEBYTES, 0);
            ::randombytes(nonce.data(), crypto_box_NONCEBYTES);
            return nonce;
        }
        
        /// Return [[public_key, secret_key]]
        std::optional<std::pair<data, data>> generate_keypair() {
            auto seckey = data(crypto_box_SECRETKEYBYTES, 0);
            auto pubkey = data(crypto_box_PUBLICKEYBYTES, 0);
            if (::crypto_box_keypair(pubkey.data(), seckey.data()) == 0)
                return {{pubkey, seckey}};
            return {};
        }

        data encrypt(const data &plain, const data &nonce, const data &pubkey, const data &seckey) {
            auto cipher = data(plain.size() + crypto_box_MACBYTES, 0);
            const auto ok = crypto_box_easy(cipher.data(), plain.data(), plain.size(), nonce.data(), pubkey.data(), seckey.data()) == 0;
            return ok ? cipher : data();
        }

        data decrypt(const data &cipher, const data &nonce, const data &pubkey, const data &seckey) {
            auto plain = data(cipher.size() - crypto_box_MACBYTES, 0);
            const auto ok = crypto_box_open_easy(plain.data(), cipher.data(), cipher.size(), nonce.data(), pubkey.data(), seckey.data()) == 0;
            return ok ? plain : data();
        }

        string b64encode(const data &dec) {
            auto enc = string(sodium_base64_ENCODED_LEN(dec.size(), sodium_base64_VARIANT_ORIGINAL), 0);
            ::sodium_bin2base64(enc.data(), enc.size(), dec.data(), dec.size(), sodium_base64_VARIANT_ORIGINAL);
            enc.resize(enc.find_first_of('\0'));
            return enc;
        }

        std::optional<data> b64decode(const string &enc) {
            auto dec = data(enc.size() * 3 / 4 + 1, 0);
            size_t data_len = 0;
            if (::sodium_base642bin(dec.data(), dec.size(), enc.data(), enc.size(),
                        nullptr, &data_len, nullptr, sodium_base64_VARIANT_ORIGINAL) == 0) {
                dec.resize(data_len);
                return dec;
            }
            return {};
        }

        void increment(data &n) {
            ::sodium_increment(n.data(), n.size());
        }
    }
    
    /**
     * The keepassxc client configuration
     */
    struct config {
        static constexpr auto CONF_PUBKEY = "public_key",
                              CONF_PRIVKEY = "private_key",
                              CONF_DATABASES = "databases";

        data public_key, private_key;
        std::unordered_map<string, string> dbs;

        /**
         * Create a new configuration
         * @note This creates the persistent key pair
         */
        static std::optional<config> create() {
            auto keys = crypto::generate_keypair();
            if (!keys)
                return {};
            auto [public_key, private_key] = keys.value();
            return config{
                .public_key = public_key,
                .private_key = private_key,
                .dbs = {},
            };
        }

        /**
         * Load configuration from a JSON object
         * @param conf The JSON object
         */
        static std::optional<config> load(const Json::Value &conf) {
            if (!conf.isMember(CONF_PUBKEY) || !conf.isMember(CONF_PRIVKEY))
                return std::nullopt;

            auto public_key = crypto::b64decode(conf[CONF_PUBKEY].asString());
            if (!public_key)
                return std::nullopt;
            
            auto private_key = crypto::b64decode(conf[CONF_PRIVKEY].asString());
            if (!private_key)
                return std::nullopt;

            return config{
                .public_key = public_key.value(),
                .private_key = private_key.value(),
                .dbs = [&conf]() {
                    auto ids = std::unordered_map<string, string>{};
                    
                    if (!conf.isMember(CONF_DATABASES))
                        return ids;

                    for (auto it = conf[CONF_DATABASES].begin(); it != conf[CONF_DATABASES].end(); it++)
                        ids.emplace(it.name(), it->asString());
                    
                    return ids;
                }(),
            };
        }

        /**
         * Write the configuration into a JSON object
         */
        void serialize(Json::Value &conf) const {
            conf[CONF_PUBKEY] = crypto::b64encode(this->public_key);
            conf[CONF_PRIVKEY] = crypto::b64encode(this->private_key);
            conf[CONF_DATABASES] = Json::objectValue;
            for (auto [dbhash, id] : this->dbs)
                conf[CONF_DATABASES][dbhash] = id;
        }
        
        /**
         * Dump the configuration as a JSON object
         */
        Json::Value serialize() const {
            Json::Value json(Json::objectValue);
            serialize(json);
            return json;
        }
    };


    /**
     * Simple, blocking client for interacting with KeePassXC
     */
    class client {
        config conf;

        data conn_pubkey = {},
             conn_privkey = {},
             remote_pubkey = {};
        string conn_id = {},
               remote_dbhash = {};

        pid_t pid = -1;
        std::unique_ptr<ko::fd::pipe> pipe = {};

        std::array<const char *, 2> proc_cmd = {"keepassxc-proxy", nullptr};

        const std::unique_ptr<Json::StreamWriter> dumper{[](){
            auto builder = Json::StreamWriterBuilder();
            builder["indentation"] = "";
            return builder.newStreamWriter();
        }()};
        const std::unique_ptr<Json::CharReader> loader{Json::CharReaderBuilder().newCharReader()};
        
        inline string dumps(const Json::Value &v) {
            auto s = std::ostringstream();
            this->dumper->write(v, &s);
            return s.str();
        }
        
        inline std::variant<Json::Value, string> loads(const string &json) {
            auto v = Json::Value();
            auto err = std::string();
            if (this->loader->parse(json.data(), json.data() + json.size(), &v, &err))
                return v;
            return err;
        }

    public:
        client(config conf) :
            conf(conf)
        {}
        
        const config &get_config() const {
            return this->conf;
        }

        void set_command(const char *cmd) {
            this->proc_cmd[0] = cmd;
        }

        bool is_connected() {
            return this->pid > 0 && this->pipe; // XXX check pipe is connected
        }

        bool is_associated() {
            return !this->remote_pubkey.empty() && !this->remote_dbhash.empty();
        }

        /**
         * Start the KeePassXC process
         * @note This generates necessary ephemeral keys and ids
         * XXX Should move the key pair into associate()?
         */
        bool connect() {
            auto keys_opt = crypto::generate_keypair();
            if (!keys_opt)
                return false;

            std::tie(this->conn_pubkey, this->conn_privkey) = keys_opt.value();
            std::tie(this->pid, this->pipe) = ko::proc::popenp(this->proc_cmd.data());
            
            this->conn_id = crypto::b64encode(crypto::generate_nonce());

            return is_connected();
        }

        Json::Value jerror(string reason) {
            auto err = Json::Value{Json::objectValue};
            err["action"] = "client-error";
            err["success"] = "false";
            err["errorCode"] = -1;
            err["error"] = reason;
            return err;
        }

        Json::Value send_message(const Json::Value &msg) {
            auto &pipe = *(this->pipe);
            auto msg_s = this->dumps(msg);

            pipe.write_bin<uint32_t>(msg_s.size());
            pipe.write(msg_s);

            auto sz_opt = pipe.read_bin<uint32_t>();
            if (!sz_opt)
                return jerror(string{"Could not read result size: "} + strerror(errno));

            auto reply = pipe.read(sz_opt.value());
            if (reply.size() < sz_opt.value())
                return jerror(string{"Could not read result: "} + strerror(errno));

            auto result_err = this->loads(reply);
            if (result_err.index())
                return jerror(string{"Could not parse message: "} + std::get<string>(result_err));

            //std::cerr << "Conversation: " << msg_s << " -> (" << sz_opt.value() << ") " << reply << std::endl;

            return std::get<0>(result_err);
        }

        Json::Value send_message_enc(const Json::Value &msg) {
            auto nonce = crypto::generate_nonce();
            auto msg_enc = crypto::encrypt(data_cast(this->dumps(msg)), nonce, this->remote_pubkey, this->conn_privkey);

            auto wrap = Json::Value(Json::objectValue);
            wrap["action"] = msg["action"];
            wrap["nonce"] = crypto::b64encode(nonce);
            wrap["clientID"] = this->conn_id;
            wrap["message"] = crypto::b64encode(msg_enc);

            auto res = this->send_message(wrap);
            
            if (res.isMember("error"))
                return res;

            crypto::increment(nonce);
            if (res.get("nonce", "").asString() != crypto::b64encode(nonce))
                return this->jerror("Invalid response nonce");

            auto cipher_opt = crypto::b64decode(res["message"].asString());
            if (!cipher_opt)
                return this->jerror("Malformed ciphertext");
            
            auto data = crypto::decrypt(cipher_opt.value(), nonce, this->remote_pubkey, this->conn_privkey);
            auto result_err = this->loads(nodata_cast(data));
            if (result_err.index())
                return this->jerror(string{"Could not parse inner message: "} + std::get<1>(result_err));

            return std::get<0>(result_err);
        }

        // ----------------------------------------------------------
        // Message types
        inline Json::Value msg_skeleton(const string &action) {
            auto msg = Json::Value{Json::objectValue};
            msg["action"] = action;
            return msg;
        }

        Json::Value send_change_public_keys() {
            auto msg = this->msg_skeleton("change-public-keys");
            msg["publicKey"] = crypto::b64encode(this->conn_pubkey);
            msg["clientID"] = this->conn_id;
            msg["nonce"] = crypto::b64encode(crypto::generate_nonce());
            return this->send_message(msg);
        }

        Json::Value send_get_databasehash() {
            return this->send_message_enc(this->msg_skeleton("get-databasehash"));
        }

        Json::Value send_associate() {
            auto msg = this->msg_skeleton("associate");
            msg["key"] = crypto::b64encode(this->conn_pubkey);
            msg["idKey"] = crypto::b64encode(this->conf.public_key);
            return this->send_message_enc(msg);
        }

        Json::Value send_test_associate(const string &id) {
            auto msg = this->msg_skeleton("test-associate");
            msg["key"] = crypto::b64encode(this->conf.public_key);
            msg["id"] = id;
            return this->send_message_enc(msg);
        }

        Json::Value send_get_logins(const string &url, const string &submitUrl=string(), bool httpAuth=false) {
            auto msg = this->msg_skeleton("get-logins");
            msg["url"] = url;
            if (!submitUrl.empty())
                msg["submitUrl"] = submitUrl;
            if (httpAuth)
                msg["httpAuth"] = httpAuth;
            msg["keys"] = Json::Value{Json::arrayValue};
            msg["keys"][0] = Json::Value{Json::objectValue};
            msg["keys"][0]["id"] = crypto::b64encode(this->conf.public_key);
            msg["keys"][0]["key"] = crypto::b64encode(this->conn_pubkey);
            return this->send_message_enc(msg);
        }

        // ----------------------------------------------------------
        // Composite functions
        /**
         * Try to associate with KeePassXC using existing IDs
         * @return A non-empty error message on failure
         */
        string try_associate() {
            // Exchange pubkeys
            auto res = this->send_change_public_keys();
            if (res.isMember("error"))
                return res["error"].asString();

            if (!res.isMember("publicKey"))
                return "publicKey not in change-public-keys reply";
            this->remote_pubkey = crypto::b64decode(res["publicKey"].asString()).value();

            // Get the dbhash
            res = this->send_get_databasehash();
            if (res.isMember("error"))
                return res["error"].asString();
            this->remote_dbhash = res["hash"].asString();
            
            // Look up database
            auto f = conf.dbs.find(this->remote_dbhash);
            if (f == conf.dbs.end())
                return "Not associated with database";
            
            // Verify association
            res = this->send_test_associate(f->second);
            if (res.get("success", "false") != "true")
                return "Key appears to have been revoked";
            return {};
        }
        
        /**
         * Try to associate with KeePassXC using either existing or new IDs
         * @return A non-empty error message on failure
         */
        string associate() {
            auto err = try_associate();
            if (err.empty())
                return {};

            auto res = this->send_associate();
            if (res.isMember("error"))
                return res["error"].asString();
            if (res.get("success", "false") != "true")
                return "Unknown error";

            this->conf.dbs.emplace(this->remote_dbhash, res["id"].asString());
            return {};
        }
    };
}
